"""Human-facing scope must agree with the revision-bound machine evidence."""
import copy
import json
from pathlib import Path

from simplecae.case import write_json
from simplecae.task import start_task, record_task_check
from simplecae.use_plan import prepare_plan

ROOT = Path(__file__).resolve().parents[1]


def scoped_plan():
    plan = json.loads((ROOT / 'examples/use-plans/manual-mechanism.json').read_text(encoding='utf-8'))
    c = plan['checks'][0]
    c['assumptions'] = ['用户授权假设：摩擦系数 0.6，未经测量', 'Agent 筛查假设：温度 23°C <not measured>']
    c['not_assessed'] = ['安装与长期蠕变没有验证']
    c['acceptance'] = '声明工况，间隙至少 0.4 mm'
    plan['unknowns'] = ['材料批次未知']
    return plan


def assert_visible_scope(page):
    assert '用户授权假设：摩擦系数 0.6，未经测量' in page
    assert 'Agent 筛查假设：温度 23°C &lt;not measured&gt;' in page
    assert '<not measured>' not in page
    assert '安装与长期蠕变没有验证' in page
    assert '声明工况，间隙至少 0.4 mm' in page
    assert '材料批次未知' in page


def test_plan_page_keeps_assumptions_acceptance_and_scope_visible(tmp_path):
    plan = scoped_plan()
    source = tmp_path / 'plan.json'
    write_json(source, plan)
    report = prepare_plan(source, tmp_path / 'plan')
    assert report['plan'] == plan and not report['worker_started']
    assert_visible_scope((tmp_path / 'plan/plan-review.html').read_text(encoding='utf-8'))


def test_task_page_keeps_assumptions_and_external_limitations_visible(tmp_path):
    plan = scoped_plan()
    task = copy.deepcopy(plan)
    task.update(schema_version='simplecae-task-1.0', sources=[str(ROOT / 'examples/preview/beam.step')])
    source = tmp_path / 'task.json'
    write_json(source, task)
    status = start_task(source, tmp_path / 'task')
    assert_visible_scope((tmp_path / 'task/task-status.html').read_text(encoding='utf-8'))
    artifact = tmp_path / 'geometry-measurement.json'
    write_json(artifact, {'gap_mm':0.5, 'method':'mathematical CAD check'})
    status = record_task_check(tmp_path / 'task', status['checks'][0]['id'],
        artifacts=[str(artifact)], outcome='pass', observations=['Measured gap 0.5 mm'],
        limitations=['只检查了一个姿态，没有进行实物测试'], summary='CAD gap exceeds 0.4 mm',
        revision_sha256=status['revision_sha256'])
    page = (tmp_path / 'task/task-status.html').read_text(encoding='utf-8')
    assert '只检查了一个姿态，没有进行实物测试' in page
    assert 'externally_recorded' in page
    assert status['whole_product_pass_available'] is False
