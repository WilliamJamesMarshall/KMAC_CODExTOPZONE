"""Run one analysis in a process that can be stopped with its Chromium children."""

import json
import logging
import sys

from .cloud_runtime import (CloudEmptyOutputRecorder, CloudLogFormatter, CloudSettings,
                            CloudStore, CloudTimingRecorder)
from .web_server import AnalysisService
from .workbook import load_knowledge_base


def main():
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(CloudLogFormatter())
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    try:
        settings = CloudSettings.from_env()
        request = json.loads(sys.stdin.buffer.read(8192))
        service = AnalysisService(load_knowledge_base(settings.workbook_path),
                                  timings=CloudTimingRecorder(),
                                  empty_outputs=CloudEmptyOutputRecorder(CloudStore(settings)))
        status, payload = service.analyze(request["url"])
    except Exception:
        logging.exception("Cloud analysis worker failed")
        status, payload = 502, {"error": "분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
                                "error_code": "analysis_failed"}
    sys.stdout.buffer.write(json.dumps([status, payload], ensure_ascii=False).encode())
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
