"""Protocol boundaries, immutable quote, optional independent RRT and retention."""
import csv
import io
from sqlalchemy import select, func, inspect
from sqlalchemy.exc import SQLAlchemyError
from extensions import db
from models import ParticipantSession, Submission, RrtInvitation, RrtResponse
from protocols import CONSENT_V4, EXPERIMENT_V4, FORM_V4, PLEDGE_VERSION, RRT_VERSION
from tests.test_original_features import FORM, ANSWERS, finish
from tests.test_stage1 import auth, session_credentials, login_admin
from rrt_routes import estimate


def create(client, *, is_test=True):
    response = client.post('/api/sessions', json={'consent': True, 'consent_version': CONSENT_V4,
        'is_test': is_test, 'client_context': {'ui_version': 'bank-application-v2'}})
    assert response.status_code == 201
    return response.get_json()['data']


def new_form(**changes):
    return dict(FORM, form_layout=FORM_V4, interest_rate=6, pledge_version=PLEDGE_VERSION,
        pledge_confirmed=True, **changes)


def submit(client, session, **changes):
    form = new_form()
    form.update(changes)
    return finish(client, session['participant_id'], session['write_token'], form=form)


def invitation(client, session):
    return client.post('/api/sessions/' + session['participant_id'] + '/rrt-invitation',
        json={'consent': True}, headers=auth(session['write_token']))


def answer(client, voucher, choice='yes', **extra):
    return client.post('/api/rrt/responses', json={'protocol_version': RRT_VERSION, 'choice': choice, **extra}, headers=auth(voucher))


def test_assigned_rate_is_server_owned_and_pledge_is_required(app, client):
    session = create(client)
    assert session['terms']['interest_rate'] == 6 and session['versions']['experiment'] == EXPERIMENT_V4
    for change in ({'interest_rate': 8.5}, {'interest_rate': True}, {'pledge_confirmed': False},
                   {'pledge_version': 'old'}, {'pledge_text': 'private text'}, {'form_layout': 'original-eight-page-v1'}):
        assert submit(client, session, **change).status_code == 400
    assert submit(client, session).status_code == 200
    with app.app_context():
        saved = db.session.scalar(select(Submission))
        assert saved.form_version == FORM_V4 and saved.payload['pledge_confirmed'] is True
        assert saved.payload['scenario_version'] == 'fixed-6-annuity-v1'
        assert 'pledge_text' not in saved.payload
        assert db.session.scalar(select(ParticipantSession)).terms_snapshot['interest_rate'] == 6


def test_old_in_progress_session_keeps_original_terms(app, client):
    identifier, token = session_credentials(client)
    assert finish(client, identifier, token).status_code == 200
    with app.app_context():
        p = db.session.scalar(select(ParticipantSession))
        assert p.terms_snapshot is None and p.submission.payload['interest_rate'] == 8.5
        assert 'pledge_confirmed' not in p.submission.payload
    html = client.get('/apply/legacy').get_data(as_text=True)
    assert 'legacy_application_v3.js' in html and '<select id="interest_rate"' in html


def test_rrt_requires_saved_application_and_separate_consent(client):
    session = create(client)
    assert invitation(client, session).status_code == 409
    assert submit(client, session).status_code == 200
    path = '/api/sessions/' + session['participant_id'] + '/rrt-invitation'
    assert client.post(path, json={'consent': True}).status_code == 401
    assert client.post(path, json={'consent': False}, headers=auth(session['write_token'])).status_code == 400
    one = invitation(client, session).get_json()['data']
    two = invitation(client, session).get_json()['data']
    assert one['voucher'] == two['voucher'] and len(one['voucher']) == 64


def test_rrt_retries_save_once_and_never_join_individual_export(app, client):
    session = create(client)
    assert submit(client, session).status_code == 200
    voucher = invitation(client, session).get_json()['data']['voucher']
    assert answer(client, voucher).status_code == 200
    assert answer(client, voucher).get_json()['data']['already_recorded'] is True
    assert answer(client, voucher, choice='no').status_code == 200
    assert invitation(client, session).get_json()['data']['voucher'] is None
    with app.app_context():
        assert db.session.scalar(select(func.count(RrtResponse.id))) == 1
        response = db.session.scalar(select(RrtResponse))
        assert response.is_test is True and response.choice == 'yes'
        fields = {col['name'] for col in inspect(db.engine).get_columns('rrt_responses')}
        assert fields == {'id', 'protocol_version', 'is_test', 'batch_day', 'choice'}
        from research_export import csv_text
        raw = csv_text([db.session.scalar(select(ParticipantSession))])
        headers = next(csv.reader(io.StringIO(raw.lstrip('\ufeff'))))
        assert not any('rrt' in key for key in headers)
        assert 'pledge_confirmed' in headers


def test_rrt_rejects_extra_tracking_and_client_group_selection(app, client):
    session = create(client)
    assert submit(client, session).status_code == 200
    voucher = invitation(client, session).get_json()['data']['voucher']
    for extra in ({'branch': 'sensitive'}, {'coin': True}, {'is_test': False}, {'participant_id': session['participant_id']}):
        assert answer(client, voucher, **extra).status_code == 400
    assert answer(client, voucher, choice=[]).status_code == 400
    assert answer(client, '0'*64).status_code == 401
    assert answer(client, voucher, choice='skipped').status_code == 200
    with app.app_context():
        assert db.session.scalar(select(RrtResponse)).choice == 'skipped'


def test_rrt_save_failure_rolls_back_redemption(app, client, monkeypatch):
    session = create(client)
    assert submit(client, session).status_code == 200
    voucher = invitation(client, session).get_json()['data']['voucher']
    with monkeypatch.context() as patch:
        patch.setattr(db.session, 'commit', lambda: (_ for _ in ()).throw(SQLAlchemyError()))
        assert answer(client, voucher).status_code == 503
    with app.app_context():
        assert db.session.scalar(select(func.count(RrtResponse.id))) == 0
        assert db.session.scalar(select(RrtInvitation)).redeemed is False
    assert answer(client, voucher).status_code == 200


def test_pledge_paste_stays_out_of_normal_features(app, client):
    session = create(client)
    path = '/api/sessions/' + session['participant_id'] + '/behavior-batches'
    events = [{'type': 'pledge_paste', 'phase': 'pledge', 'page': 6},
        {'type': 'paste_event', 'phase': 'application', 'field': 'total_debt'}]
    assert client.post(path, json={'batch_id': 'pledge-batch-001', 'batch_seq': 1, 'events': events}, headers=auth(session['write_token'])).status_code == 200
    with app.app_context():
        metrics = db.session.scalar(select(ParticipantSession)).behavior_summary.metrics
        assert metrics['pledge']['paste_count'] == 1
        assert metrics['fields']['total_debt']['paste_count'] == 1
        assert 'pledge_confirmed' not in metrics['fields']
    assert client.post(path, json={'batch_id': 'pledge-batch-002', 'batch_seq': 2,
        'events': [{'type': 'pledge_paste', 'phase': 'application'}]}, headers=auth(session['write_token'])).status_code == 400


def test_rrt_group_estimation_and_test_filter(app, client):
    assert estimate(40, 60, 2)['estimate_raw'] == 0.30000000000000004
    edge = estimate(0, 10, 0)
    assert edge['estimate_raw'] == -0.5 and edge['estimate_constrained'] == 0
    assert edge['ci95_raw'][0] < 0 and estimate(0, 0, 1)['estimate_raw'] is None
    assert client.get('/admin/api/rrt-summary').status_code == 401
    with app.app_context():
        from datetime import date
        db.session.add_all([RrtResponse(protocol_version=RRT_VERSION, is_test=False, batch_day=date.today(), choice='no'),
            RrtResponse(protocol_version=RRT_VERSION, is_test=True, batch_day=date.today(), choice='yes')])
        db.session.commit()
    login_admin(client)
    data = client.get('/admin/api/rrt-summary').get_json()['data']
    assert data['kind'] == 'formal' and data['no'] == 1 and data['yes'] == 0
    assert client.get('/admin/api/rrt-summary?kind=test').get_json()['data']['yes'] == 1
    assert client.get('/admin/api/rrt-summary?kind=all').status_code == 400
    assert client.get('/admin/rrt').status_code == 200
