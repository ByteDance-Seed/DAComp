#!/usr/bin/env python3
"""
Unified CLI for DA-Comp DE evaluation.
"""
import argparse
import json
import logging
from pathlib import Path

from utils import PipelineEvaluator, batch_evaluate

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def run_single(args: argparse.Namespace) -> None:
    evaluator = PipelineEvaluator(args.config, force_rebuild=args.force_rebuild, mode=args.mode)
    result = evaluator.evaluate_example(args.example_id, args.gold_dir, args.pred_dir)
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"\nResults saved to: {args.output}")
    print(f"\nFinal Score: {result['final_score']:.2f}")
    print(f"Evaluation Level: {result.get('evaluation_level', 'unknown')}")


def run_batch(args: argparse.Namespace) -> None:
    batch_evaluate(args.config, args.gold_dir, args.pred_dir, args.examples, args.output_dir, force_rebuild=args.force_rebuild, mode=args.mode)

def main():
    parser = argparse.ArgumentParser(description="Unified CLI for data engineering evaluation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # single command
    single = subparsers.add_parser("single", help="Single example evaluation")
    single.add_argument("--config", default="evaluation_config_compare.yaml")
    single.add_argument("--gold_dir", default="./gold")
    single.add_argument("--pred_dir", required=True)
    single.add_argument("--example_id", required=True)
    single.add_argument("--output", help="Output file path")
    single.add_argument("--force-rebuild", action="store_true", help="Force rebuild database before running (default: no rebuild)")
    single.add_argument("--mode", choices=["cfs", "cs"], default="cfs", help="Evaluation mode: cfs or cs (default cfs)")
    single.set_defaults(func=run_single)

    # batch command
    batch = subparsers.add_parser("batch", help="Batch evaluation")
    batch.add_argument("--config", default="evaluation_config_compare.yaml")
    batch.add_argument("--gold_dir", default="./gold")
    batch.add_argument("--pred_dir", required=True)
    batch.add_argument("--examples", nargs="+", help="Example ID list to evaluate (evaluate all if omitted)")
    batch.add_argument("--output_dir", default="results", help="Output directory")
    batch.add_argument("--force-rebuild", action="store_true", help="Force rebuild database before running (default: no rebuild)")
    batch.add_argument("--mode", choices=["cfs", "cs"], default="cfs", help="Evaluation mode: cfs or cs (default cfs)")
    batch.set_defaults(func=run_batch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
