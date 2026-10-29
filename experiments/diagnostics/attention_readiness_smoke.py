"""Audit existing building blocks; this is NOT the continual-learning gate."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.learning import LearningSystem
from core.peripheral import PeripheralManager
from core.attention_loop import AttentionLoop
from core.session import SessionManager
from data.gen_base import GenBaseDB
from drivers.text_driver import TextDriver
from drivers.sequence_driver import SequenceDriver


def audit():
    system=LearningSystem(feature_tolerance=.15)
    mgr=PeripheralManager(system)
    mgr.register(TextDriver('alpha'),priority=10)
    mgr.register(TextDriver('beta'),priority=0)
    loop=AttentionLoop(system,mgr)
    loop.load_buffer('кот сидит на крыше кот спит','alpha')
    loop.load_buffer('пёс сидит у двери пёс спит','beta')
    steps=loop.run_until_empty(max_steps=100)
    routing=[s.driver_queried for s in steps if s.driver_queried]
    first_beta=routing.index('beta') if 'beta' in routing else None
    fixed_order=first_beta is not None and all(x=='alpha' for x in routing[:first_beta]) and all(x=='beta' for x in routing[first_beta:])
    idle=loop.step().outcome
    nodes_before=system.base.size()
    steps_before=system.engine.step_count
    mgr.register(SequenceDriver('numbers',sequence=[1,2,3,1,2,4]),priority=-1)
    sequence_results=mgr.process('numbers')
    with tempfile.TemporaryDirectory(prefix='firstagi_readiness_') as directory:
        sm=SessionManager(directory)
        sm.save('own_trusted_snapshot',system)
        restored,_=sm.load('own_trusted_snapshot')
        pickle_nodes=restored.base.size()==system.base.size()
        pickle_features=len(restored.engine._features)==len(system.engine._features)
        db=GenBaseDB(Path(directory)/'gens.db')
        db.checkpoint(system.base)
        fresh=LearningSystem(feature_tolerance=.15)
        loaded=db.load(fresh.base)
        sqlite_features=len(fresh.engine._features)
        missing=sum(fid not in fresh.engine._features for g in fresh.base.all() for fid in g.feature_chain)
        db.close()
    return {'schema':'firstagi.attention-readiness/v1',
            'scope':'Existing component smoke, no AGI, autonomy, retention or inheritance claim',
            'commands':'python experiments/diagnostics/attention_readiness_smoke.py --out <new-file>',
            'channels':{'ids':['alpha','beta'],'routing':routing,'fixed_priority_order_observed':fixed_order,
                        'learned_channel_selection_proven':False},
            'core':{'processed_steps_before_sequence':steps_before,'nodes_before_sequence':nodes_before,
                    'nodes_after_sequence':system.base.size(),'numeric_driver_steps':len(sequence_results),
                    'empty_buffer_outcome':idle},
            'persistence':{'own_pickle_node_count_preserved':pickle_nodes,'own_pickle_feature_count_preserved':pickle_features,
                           'sqlite_loaded_nodes':loaded,'sqlite_restored_engine_feature_count':sqlite_features,
                           'sqlite_unresolved_feature_references':missing,
                           'note':'GenBaseDB.load(base) is a Gen-store API; this does not test any additional feature-restoration adapter.'},
            'not_tested':['task success','multi-channel context continuity','independent action choice',
                          'interrupt vs disconfirmation','revision publication','topology-only inheritance',
                          'local-frontier complexity','long-duration bounded memory']}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    result=audit()
    try:
        result['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    except (OSError,subprocess.CalledProcessError): result['source_commit']='unavailable'
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
