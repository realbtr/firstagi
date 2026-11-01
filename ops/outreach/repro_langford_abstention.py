"""Offline extraction of the reviewed main() only; no peer imports or live LLM."""
import ast
import argparse
import tempfile
import contextlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True)
args = parser.parse_args()
work = tempfile.TemporaryDirectory(prefix='firstagi-langford-offline-')
root = Path(work.name)
source = args.source.read_text(encoding='utf-8')
main_node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'main')
code = compile(ast.Module(body=[main_node], type_ignores=[]), 'reviewed_main_excerpt', 'exec')


def run(first_error):
    class FakeLLM:
        def __init__(self, **kwargs):
            pass

        def invoke(self, name):
            if first_error or name == 'should-engage':
                raise RuntimeError('synthetic unavailable backend')
            return NS(response_metadata={'eval_count': 3})

    cases = [NS(name='should-abstain', kind='reply', want_abstain=True, held_out=False),
             NS(name='should-engage', kind='reply', want_abstain=False, held_out=False)]
    output = root / ('synthetic_first_error.json' if first_error else 'synthetic_false_pass.json')
    scope = dict(os=os, time=NS(time=lambda: 0), json=json, MODEL='fake-offline', BASE='unused',
                 TEMP=0, REPEATS=1, CASES=cases, OUT=output, ChatOllama=FakeLLM,
                 COMMENT_CHAR_CAP=2000, POST_CHAR_CAP=4000, build=lambda c: c.name,
                 usable_reply=lambda out, cap: NS(text=None, reason='PASS', model_abstained=True))
    exec(code, scope)
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            result = scope['main']()
        except Exception as exc:
            return {'first_error': first_error, 'exception': type(exc).__name__}
    data = json.loads(output.read_text())
    return {'first_error': first_error, 'exit_code': result, 'verdict': data['summary']['verdict'],
            'error_rows': sum(r['error'] is not None for r in data['rows']),
            'engage_row_correct': data['rows'][1]['correct']}


if __name__ == '__main__':
    result = [run(True), run(False)]
    assert result[0]['exception'] == 'UnboundLocalError'
    assert result[1]['verdict'].startswith('PASS') and result[1]['engage_row_correct']
    print(json.dumps(result))
