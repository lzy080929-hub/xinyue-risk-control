from __future__ import annotations
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import create_app
from extensions import db
from flask_migrate import upgrade
from models import BehaviorBatch, ParticipantSession, ScaleAnswer, Submission
from sqlalchemy import func, select
from tests.conftest import make_test_config
from config import CONSENT_VERSION
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server, WSGIRequestHandler


class Quiet(WSGIRequestHandler):
    def log_request(self, *args):
        pass


def main():
    artifacts = ROOT / 'verification_artifacts'
    artifacts.mkdir(exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='bank-interface-', dir=artifacts))
    cfg = make_test_config(out / 'verification.sqlite3')
    cfg.update(ADMIN_USERNAME='', ADMIN_PASSWORD_HASH='', LOCAL_SETUP_FILE=str(out / 'local-test.env'))
    application = create_app(cfg)
    with application.app_context():
        upgrade(directory=str(ROOT / 'migrations'))
    server = make_server('127.0.0.1', 0, application, threaded=True, request_handler=Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    report = {'database_isolated': True, 'production_data_modified': False, 'output_directory': str(out)}
    page_errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True)
            try:
                context = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
                page = context.new_page()
                page.on('pageerror', lambda error: page_errors.append(str(error)))
                page.goto(base + '/?test=1&source=browser_check', wait_until='networkidle')
                assert page.locator('.form-page').count() == 8
                assert page.locator('#loan-application-form').get_attribute('data-ui-version') == 'bank-application-v1'
                assert page.evaluate("getComputedStyle(document.querySelector('.buttons')).position") == 'relative'
                desktop = browser.new_page(viewport={'width': 1440, 'height': 1100})
                desktop.goto(base + '/?test=1', wait_until='networkidle')
                assert desktop.evaluate('document.documentElement.scrollWidth <= innerWidth')
                desktop.screenshot(path=str(out / '00-desktop-consent.png'), full_page=True)
                desktop.close()
                for width in (320, 360, 390):
                    page.set_viewport_size({'width': width, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(out / '01-original-consent.png'), full_page=True)
                with application.app_context():
                    assert db.session.scalar(select(func.count(ParticipantSession.id))) == 0
                page.check('#consent_agreed')
                page.click('#next-btn')
                expect(page.locator('[data-page="2"]')).to_be_visible()
                public_id = page.locator('#participant-code').inner_text()
                assert public_id.startswith('TEST-')
                page.fill('#name', '试填同学')
                page.fill('#age', '20')
                page.select_option('#education', 'bachelor')
                page.fill('#occupation', '大学生')
                page.locator('#occupation').evaluate("el => { el.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,inputType:'insertCompositionText'})); el.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'生'})); el.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText'})); }")
                page.click('#next-btn')
                expect(page.locator('[data-page="3"]')).to_be_visible()
                expect(page.locator('[aria-current="step"]')).to_contain_text('申请填写')
                assert page.locator('#application-progress').get_attribute('value') == '3'
                page.locator('#monthly_income').press_sequentially('20000')
                page.locator('#monthly_income').press('Backspace')
                page.fill('#total_debt', '5000')
                page.locator('#total_debt').dispatch_event('paste')
                expect(page.locator('#debt_ratio')).to_have_value('250.00')
                page.screenshot(path=str(out / '02-original-finance.png'), full_page=True)
                page.click('#prev-btn')
                page.click('#next-btn')
                page.focus('#monthly_income')
                page.wait_for_timeout(300)
                # Deterministic hidden/visible lifecycle check in a real browser DOM.
                page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.qaHidden||false});window.qaHidden=true;document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_timeout(1200)
                page.evaluate("window.qaHidden=false;document.dispatchEvent(new Event('visibilitychange'))")
                page.wait_for_timeout(300)
                page.click('#next-btn')
                page.fill('#loan_amount', '12000')
                page.fill('#loan_term', '12')
                page.fill('#loan_purpose', '学习设备')
                page.click('#next-btn')
                page.select_option('#interest_rate', '8.5')
                page.check('#interest_rate_confirmed')
                page.click('#next-btn')
                expect(page.locator('#application-review')).to_contain_text('12000元')
                page.check('#final_confirmed')
                page.click('#next-btn')
                expect(page.locator('[data-page="7"]')).to_be_visible()
                page.click('#next-btn')
                expect(page.locator('#form-error')).to_be_visible()
                for number in range(1, 16):
                    value = 1 if number == 7 else 4
                    page.locator(f'#scale-q-{number:02d} input[value="{value}"]').check()
                assert page.locator('#scale-q-01 input:checked + span').evaluate("el => getComputedStyle(el).backgroundColor") == 'rgb(238, 244, 251)'
                page.screenshot(path=str(out / '05-survey-selection.png'), full_page=True)
                page.click('#next-btn')
                for number in range(16, 30):
                    value = 2 if number == 29 else 4
                    page.locator(f'#scale-q-{number:02d} input[value="{value}"]').check()
                expect(page.locator('#save-state')).to_have_text('草稿已保存', timeout=15000)
                page.reload(wait_until='networkidle')
                expect(page.locator('[data-page="8"]')).to_be_visible()
                assert page.locator('input[name^="rs_q"]:checked').count() == 29
                expect(page.locator('#loan_amount')).to_have_value('12000')
                assert page.locator('#final_confirmed').is_checked()
                page.click('#prev-btn')
                page.click('#next-btn')
                report['eight_page_flow_and_refresh'] = True
                print('Browser: original pages, required answers, input, paste and refresh passed', flush=True)
                local = page.evaluate("JSON.parse(sessionStorage.getItem('xinyue.original-eight-page.v3'))")
                failed = {'once': False}
                def fail_once(route):
                    if not failed['once']:
                        failed['once'] = True
                        route.abort('failed')
                    else:
                        route.continue_()
                page.route('**/api/sessions/*/submit', fail_once)
                page.click('#submit-btn')
                expect(page.locator('#form-error')).to_be_visible(timeout=20000)
                expect(page.locator('#submit-message')).to_be_hidden()
                assert page.locator('input[name^="rs_q"]:checked').count() == 29
                page.click('#submit-btn')
                expect(page.locator('#submit-message')).to_be_visible(timeout=20000)
                receipt = page.locator('#receipt-id').inner_text()
                assert receipt and receipt != '—'
                assert page.locator('#behavior-receipt').inner_text() == '本次填写记录已同步保存。'
                page.screenshot(path=str(out / '03-original-success.png'), full_page=True)
                report['network_failure_retry_receipt'] = True
                with application.app_context():
                    participant = db.session.execute(select(ParticipantSession)).scalar_one()
                    summary = participant.behavior_summary
                    assert summary.status == 'complete'
                    assert summary.received_batches > 1
                    metrics = summary.metrics
                    assert metrics['fields']['monthly_income']['delete_count'] >= 1
                    assert metrics['fields']['occupation']['input_count'] == 2
                    assert metrics['fields']['total_debt']['paste_count'] == 1
                    assert metrics['hidden_duration_ms'] >= 1000
                    assert metrics['back_navigation_count'] >= 1
                    assert metrics['resume_count'] == 1
                    assert len(participant.scale_answers) == 29
                    assert participant.submission.payload['total_debt'] == 5000
                    assert participant.submission.payload['debt_ratio'] == 250
                    assert participant.client_context['ui_version'] == 'bank-application-v1'
                    assert 'interface_changed_during_session' not in metrics['quality_flags']
                    report['behavior'] = {key: metrics[key] for key in ('application_visible_ms','survey_visible_ms','hidden_duration_ms','resume_count','back_navigation_count')}
                    report['received_batches'] = summary.received_batches
                    assert all(set(event) <= {'type','phase','field','page','client_time_ms','duration_ms','visibility'} for batch in participant.behavior_batches for event in batch.events)
                duplicate = context.request.post(base + '/api/sessions/' + public_id + '/submit', headers={'Authorization': 'Bearer ' + local['token']}, data={'submission_key': local['submissionKey']})
                assert duplicate.status == 200 and duplicate.json()['data']['receipt_id'] == receipt
                report['incremental_behavior_and_deduplication'] = True
                admin = browser.new_page(viewport={'width': 1280, 'height': 1000})
                admin.goto(base + '/admin/login')
                admin.get_by_role('link', name='首次设置本机管理员').click()
                admin.fill('#username', 'review_admin')
                admin.fill('#password', 'Browser-local-only-test-42')
                admin.fill('#confirm', 'Browser-local-only-test-42')
                admin.get_by_role('button', name='保存并前往登录').click()
                expect(admin).to_have_url(base + '/admin/login')
                admin.fill('#username', 'review_admin')
                admin.fill('#password', 'Browser-local-only-test-42')
                admin.locator('button[type="submit"]').click()
                expect(admin).to_have_url(base + '/admin/')
                admin.goto(base + '/admin/participants/' + public_id)
                assert admin.locator('.answer-table tbody tr').count() == 29
                totals = [admin.locator('.score-card .score-total strong').nth(i).inner_text().strip() for i in range(4)]
                assert totals == ['35','32','32','22'], totals
                expect(admin.locator('#behavior-results')).to_contain_text('monthly_income')
                admin.screenshot(path=str(out / '04-admin-behavior.png'), full_page=True)
                admin.goto(base + '/admin/')
                export_form = admin.locator('form[action="/admin/export.csv"]')
                export_form.locator('select[name="kind"]').select_option('test')
                with admin.expect_download() as download:
                    export_form.get_by_role('button', name='导出分析CSV').click()
                csv_file = out / 'verified-analysis.csv'
                download.value.save_as(str(csv_file))
                rows = list(csv.DictReader(io.StringIO(csv_file.read_text(encoding='utf-8-sig'))))
                assert len(rows) == 1 and rows[0]['participant_id'] == public_id
                assert rows[0]['behavior_status'] == 'complete'
                assert rows[0]['total_debt'] == '5000'
                assert rows[0]['ui_version'] == 'bank-application-v1'
                assert rows[0]['ATR_total'] == '35' and rows[0]['LRI_total'] == '22'
                csrf = admin.locator('input[name="csrf_token"]').first.get_attribute('value')
                events = admin.request.post(base + '/admin/export.csv', form={'csrf_token': csrf, 'kind': 'test', 'status':'submitted', 'format':'events'})
                event_rows = list(csv.DictReader(io.StringIO(events.text().lstrip('\ufeff'))))
                assert event_rows and all(row['phase'] == 'application' for row in event_rows)
                report['admin_setup_scoring_csv'] = True
                created = context.request.post(base + '/api/sessions', data={'consent':True,'consent_version':CONSENT_VERSION,'is_test':True}).json()['data']
                expect(admin.locator('#records-body')).to_contain_text(created['participant_id'], timeout=15000)
                report['admin_auto_refresh'] = True
                # Old in-progress tabs keep answers and obtain an explicit cross-interface quality flag.
                legacy_tab = context.new_page()
                legacy_tab.on('pageerror', lambda error: page_errors.append(str(error)))
                legacy_tab.goto(base + '/?test=1')
                legacy_tab.check('#consent_agreed')
                legacy_tab.click('#next-btn')
                expect(legacy_tab.locator('[data-page="2"]')).to_be_visible()
                legacy_tab.fill('#age', '22')
                # Seed a legacy snapshot at document start: current pagehide handlers
                # would otherwise rewrite its version just before a normal reload.
                legacy_tab.add_init_script("const k='xinyue.original-eight-page.v3';const s=JSON.parse(sessionStorage.getItem(k));if(s){delete s.uiVersion;sessionStorage.setItem(k,JSON.stringify(s))}")
                legacy_tab.reload(wait_until='networkidle')
                expect(legacy_tab.locator('#age')).to_have_value('22')
                legacy_tab.wait_for_timeout(5500)
                legacy_id = legacy_tab.locator('#participant-code').inner_text()
                with application.app_context():
                    restored = db.session.scalar(select(ParticipantSession).where(ParticipantSession.public_id == legacy_id))
                    assert 'interface_changed_during_session' in restored.behavior_summary.metrics['quality_flags']
                legacy_tab.close()
                report['cross_interface_resume_preserves_answers_and_flags'] = True
                report['interface_version'] = 'bank-application-v1'
                report['subscale_totals'] = totals
                assert not page_errors, page_errors
                report['javascript_errors'] = page_errors
                report['passed'] = True
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
