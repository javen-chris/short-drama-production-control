"""Bind, independently review, or validate a final packet. Never submits video."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from production_control.final_submission import bind_packet, load_approved_packet
from production_control.final_packet_qa import review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['bind', 'qa', 'check'])
    parser.add_argument('--packet', required=True)
    parser.add_argument('--project-root')
    parser.add_argument('--run')
    parser.add_argument('--qa-report')
    parser.add_argument('--output-directory')
    args = parser.parse_args()
    try:
        if args.action == 'bind':
            if not args.project_root or not args.run:
                parser.error('bind requires --project-root and --run')
            result = bind_packet(args.project_root, args.run, args.packet)
        elif args.action == 'qa':
            if not args.output_directory:
                parser.error('qa requires a fresh --output-directory')
            result = review(args.packet, args.output_directory)
        else:
            if not args.qa_report:
                parser.error('check requires --qa-report')
            load_approved_packet(args.packet, args.qa_report)
            result = {'status': 'PACKET_AND_CONTENT_QA_VALID', 'provider_submit': False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'REJECTED', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
