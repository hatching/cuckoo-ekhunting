# Copyright (C) 2016-2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import os

from django.http import JsonResponse, Http404
from django.template.defaultfilters import filesizeformat

from cuckoo.core.task import Task
from cuckoo.misc import cwd
from cuckoo.web.utils import api_post, json_error_response

class ExportApi:
    @api_post
    def export_estimate_size(request, body):
        task_id = body.get('task_id')
        taken_dirs = body.get("dirs", [])
        taken_files = body.get("files", [])

        if not taken_dirs and not taken_files:
            return JsonResponse({"size": 0, "size_human": "-"}, safe=False)

        if not task_id:
            return json_error_response("invalid task_id")

        size = Task.estimate_export_size(
            task_id=task_id, taken_dirs=taken_dirs, taken_files=taken_files
        )
        size_response = {
            "size": int(size),
            "size_human": filesizeformat(size)
        }

        return JsonResponse(size_response, safe=False)

    @api_post
    def get_files(request, body):
        task_id = body.get('task_id', None)

        if not task_id:
            return json_error_response("invalid task_id")

        if not os.path.isfile(cwd("reports", "report.json", analysis=task_id)):
            raise Http404("Task %s: report.json not found" % task_id)

        dirs, files = Task.get_files(task_id)

        return JsonResponse({"dirs": dirs, "files": files}, safe=False)
