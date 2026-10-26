"""Real Chrome: fixed terms, pledge, return/resume, private RRT and old drafts."""
from __future__ import annotations
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flask_migrate import upgrade
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select, func
from werkzeug.serving import make_server, WSGIRequestHandler
from app import create_app
from extensions import db
from models import ParticipantSession, RrtResponse
from tests.conftest import make_test_config, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD
from protocols import PLEDGE_TEXT, EXPERIMENT_V4


class Quiet(WSGIRequestHandler):
    def log_request(self, *args):
        pass


def main():
    out = Path(tempfile.mkdtemp(prefix='fixedrate-', dir=ROOT / 'verification_artifacts'))
    application = create_app(make_test_config(out / 'verification.sqlite3'))
    with application.app_context():
        upgrade(directory=str(ROOT / 'migrations'))
    server = make_server('127.0.0.1', 0, application, threaded=True, request_handler=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    report = {'database_isolated': True, 'production_data_modified': False, 'output_directory': str(out)}
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True)
            try:
                def run_flow(branch, *, retry=False):
                    context = browser.new_context(viewport={'width':390,'height':900}, is_mobile=True, has_touch=True)
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base + '/apply?test=1&source=fixedrate_browser', wait_until='networkidle')
                    assert page.locator('select#interest_rate').count() == 0
                    assert page.locator('.home-button').get_attribute('href') == '/'
                    assert page.locator('#interest_rate').get_attribute('readonly') is not None
                    if retry:
                        with application.app_context():
                            assert db.session.scalar(select(func.count(ParticipantSession.id))) == 0
                        page.locator('.home-button').click()
                        expect(page.locator('h1')).to_contain_text('学会管理生活费')
                        page.goto(base + '/apply?test=1')
                    for width in (320,390,1440):
                        page.set_viewport_size({'width':width,'height':900})
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.set_viewport_size({'width':390,'height':900})
                    page.check('#consent_agreed'); page.click('#next-btn')
                    expect(page.locator('[data-page="2"]')).to_be_visible()
                    identifier = page.locator('#participant-code').inner_text()
                    page.fill('#age','20'); page.select_option('#education','bachelor'); page.fill('#occupation','大学生')
                    if retry:
                        page.locator('.home-button').click()
                        expect(page.locator('[data-resume-banner]')).to_be_visible()
                        page.goto(base + '/apply?test=1')
                        expect(page.locator('#age')).to_have_value('20')
                    page.click('#next-btn')
                    page.fill('#monthly_income','2000'); page.fill('#total_debt','0'); page.click('#next-btn')
                    page.fill('#loan_amount','10000'); page.fill('#loan_term','12'); page.fill('#loan_purpose','学习设备')
                    page.locator('#loan_purpose').dispatch_event('paste')
                    page.click('#next-btn')
                    expect(page.locator('#quote-monthly')).to_have_text('860.66 元')
                    expect(page.locator('#quote-total')).to_have_text('10,327.97 元')
                    expect(page.locator('#quote-effective')).to_have_text('6.17%')
                    for width in (320,390,1440):
                        page.set_viewport_size({'width':width,'height':900})
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.set_viewport_size({'width':390,'height':900})
                    if retry: page.screenshot(path=str(out / '01-fixed-quote-mobile.png'),full_page=True)
                    page.check('#interest_rate_confirmed'); page.click('#next-btn')
                    page.click('#next-btn')
                    expect(page.locator('[data-page="6"]')).to_be_visible()
                    page.evaluate("() => { navigator.clipboard.writeText=async()=>{throw new Error('not allowed')}; }")
                    page.click('#copy-pledge')
                    expect(page.locator('#pledge-status')).to_contain_text('长按')
                    page.locator('#pledge-text').dispatch_event('paste')
                    page.fill('#pledge-text',PLEDGE_TEXT)
                    page.check('#pledge_confirmed'); page.check('#final_confirmed')
                    if retry:
                        stored = page.evaluate("JSON.parse(sessionStorage.getItem('xinyue.original-eight-page.v4'))")
                        assert 'pledge_text' not in json.dumps(stored) and PLEDGE_TEXT not in json.dumps(stored,ensure_ascii=False)
                        page.reload(wait_until='networkidle')
                        expect(page.locator('#pledge_confirmed')).to_be_checked()
                        expect(page.locator('#pledge-text')).to_have_value(PLEDGE_TEXT)
                        page.screenshot(path=str(out / '02-pledge-mobile.png'),full_page=True)
                    page.click('#next-btn')
                    for number in range(1,16): page.locator(f'#scale-q-{number:02d} input[value="4"]').check()
                    page.click('#next-btn')
                    for number in range(16,30): page.locator(f'#scale-q-{number:02d} input[value="4"]').check()
                    page.click('#submit-btn')
                    expect(page.locator('#submit-message')).to_be_visible()
                    expect(page.locator('#behavior-receipt')).to_have_text('本次填写记录已同步保存。')
                    receipt = page.locator('#receipt-id').inner_text()
                    with application.app_context():
                        participant = db.session.scalar(select(ParticipantSession).where(ParticipantSession.public_id==identifier))
                        assert participant.experiment_version == EXPERIMENT_V4
                        before_batches = len(participant.behavior_batches)
                        assert participant.behavior_summary.metrics['pledge']['paste_count'] == 1
                        assert 'pledge_confirmed' not in participant.behavior_summary.metrics['fields']
                        assert participant.behavior_summary.metrics['fields']['loan_purpose']['paste_count'] == 1
                    page.click('#rrt-start')
                    expect(page.locator('#rrt-status')).to_contain_text('自愿勾选')
                    # Only RRT's two-byte draw is controlled; application IDs stay random.
                    page.evaluate("""([branch])=>{const original=crypto.getRandomValues.bind(crypto);crypto.getRandomValues=(a)=>{if(a.length===2){a[0]=branch;a[1]=1;return a;}return original(a)}}""",[branch])
                    page.check('#rrt-consent'); page.click('#rrt-start')
                    expect(page.locator('#rrt-question-area')).to_be_visible()
                    text = page.locator('#rrt-private-question').inner_text()
                    assert ('过去12个月' in text) if branch else ('正面' in text and '独立公平' in text)
                    bodies = []
                    page.on('request', lambda req: bodies.append(req.post_data_json) if req.url.endswith('/api/rrt/responses') else None)
                    page.check('input[name="rrt-choice"][value="yes"]' if not branch else 'input[name="rrt-choice"][value="no"]')
                    if retry:
                        page.route('**/api/rrt/responses',lambda route: route.abort(),times=1)
                        page.click('#rrt-send')
                        expect(page.locator('#rrt-status')).to_contain_text('保留当前页面重试')
                        expect(page.locator('#receipt-id')).to_have_text(receipt)
                        assert page.locator('#rrt-private-question').inner_text()==text
                    page.click('#rrt-send')
                    expect(page.locator('#rrt-status')).to_contain_text('独立调查已保存')
                    assert all(set(body)=={'choice','protocol_version'} for body in bodies)
                    assert page.locator('#rrt-private-question').inner_text()==''
                    assert page.evaluate("Object.keys(sessionStorage).every(k=>!k.includes('rrt'))")
                    with application.app_context():
                        p = db.session.scalar(select(ParticipantSession).where(ParticipantSession.public_id==identifier))
                        assert len(p.behavior_batches)==before_batches
                    if retry: page.screenshot(path=str(out / '03-rrt-saved-mobile.png'),full_page=True)
                    context.close()

                run_flow(0,retry=True)
                run_flow(1)
                legacy = browser.new_page()
                legacy.goto(base + '/apply/legacy?test=1')
                legacy.check('#consent_agreed'); legacy.click('#next-btn')
                expect(legacy.locator('[data-page="2"]')).to_be_visible()
                legacy.fill('#age','25')
                legacy.goto(base + '/apply?test=1',wait_until='networkidle')
                expect(legacy).to_have_url(base + '/apply/legacy?test=1')
                expect(legacy.locator('#age')).to_have_value('25')
                legacy.click('#start-new-application')
                expect(legacy.locator('[data-page="1"]')).to_be_visible()
                assert legacy.locator('select#interest_rate').count()==0
                assert legacy.evaluate("JSON.parse(sessionStorage.getItem('xinyue.original-eight-page.v3')).form.age")=='25'
                legacy.close()
                admin = browser.new_page()
                admin.goto(base+'/admin/login'); admin.fill('#username',TEST_ADMIN_USERNAME); admin.fill('#password',TEST_ADMIN_PASSWORD)
                admin.locator('button[type="submit"]').click()
                admin.goto(base+'/admin/rrt?kind=test')
                expect(admin.locator('h1')).to_have_text('RRT群体调查')
                data = admin.request.get(base+'/admin/api/rrt-summary?kind=test').json()['data']
                assert data['yes']==1 and data['no']==1 and data['valid']==2
                admin.screenshot(path=str(out/'04-admin-rrt.png'),full_page=True)
                assert not errors, errors
                report.update(fixed_quote_and_costs=True, home_and_same_tab_resume=True, pledge_required_and_restore=True,
                    pledge_text_not_uploaded_or_stored=True, pledge_paste_separate=True,
                    rrt_both_private_branches=True, rrt_retry_preserves_main_receipt=True,
                    rrt_no_extra_behavior_batches=True, rrt_upload_only_mixed_choice=True,
                    admin_rrt_groups=True, legacy_restore_and_start_new_preserves_draft=True, javascript_errors=errors, passed=True)
            finally: browser.close()
    finally:
        server.shutdown(); thread.join(timeout=5); server.server_close()
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
