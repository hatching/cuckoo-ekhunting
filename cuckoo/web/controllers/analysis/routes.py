# Copyright (C) 2016-2017 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import re

from django.http import HttpResponse
from django.shortcuts import redirect
from django.core.urlresolvers import reverse

from cuckoo.core.task import Task
from cuckoo.web.controllers.analysis.analysis import AnalysisController
from cuckoo.web.utils import view_error, render_template

submit_task = Task()

class AnalysisRoutes:
    @staticmethod
    def recent(request):
        return render_template(request, "analysis/index.html")

    @staticmethod
    def detail(request, task_id, page):
        report = AnalysisController.get_report(task_id)

        pages = {
            "summary": "summary/index",
            "static": "static/index",
            "extracted": "extracted/index",
            "behavior": "behavior/index",
            "network": "network/index",
            "misp": "misp/index",
            "dropped_files": "dropped/dropped_files",
            "dropped_buffers": "dropped/dropped_buffers",
            "memory": "memory/index",
            "procmemory": "procmemory/index",
            "options": "options/index",
            "feedback": "feedback/index"
        }

        if page in pages.keys():
            return render_template(
                request, "analysis/pages/%s.html" % pages[page],
                report=report, page=page
            )
        else:
            return view_error(
                request, msg="Analysis subpage not found", status=404
            )

    @staticmethod
    def redirect_default(request, task_id):
        if not isinstance(task_id, (unicode, str)):
            task_id = str(task_id)

        return redirect(reverse(
            "analysis",
            args=(re.sub(r"\^d+", "", task_id), "summary")),
            permanent=False
        )

    @staticmethod
    def export(request, task_id):
        if request.method == "POST":
            taken_dirs = request.POST.getlist("dirs")
            taken_files = request.POST.getlist("files")

            if len(taken_dirs) + len(taken_files) < 1:
                return view_error(
                    request, "Please select at least one directory or file"
                    " to be exported."
                )

            zip = Task.create_zip(
                task_id=task_id, taken_dirs=taken_dirs, taken_files=taken_files
            )
            if not zip:
                return view_error(request, "Failed to create zip.")

            response = HttpResponse(
                zip.getvalue(), content_type="application/zip"
            )
            response["Content-Disposition"] = "attachment; filename=%s.zip"\
                                              % task_id

            return response

        report = AnalysisController.get_report(task_id)

        dirs, files = Task.get_files(task_id)
        return render_template(
            request, "analysis/export.html", report=report, dirs=dirs,
            files=files
        )

    @staticmethod
    def reboot(request, task_id):
        task_obj = submit_task.add_reboot(task_id=task_id)
        return render_template(request, "submission/reboot.html",
                               task_id=task_id, task_obj=task_obj,
                               baseurl=request.build_absolute_uri("/")[:-1])
