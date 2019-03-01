# Copyright (C) 2010-2013 Claudio Guarnieri.
# Copyright (C) 2014-2019 Cuckoo Foundation.
# This file is part of Cuckoo Sandbox - http://www.cuckoosandbox.org
# See the file 'docs/LICENSE' for copying permission.

import os
import subprocess

from lib.common.abstracts import Package
from lib.common.rand import random_string

import logging

log = logging.getLogger(__name__)


class Firefox(Package):
    """Firefox analysis package."""
    PATHS = [
        ("ProgramFiles", "Mozilla Firefox", "firefox.exe"),
    ]

    # Preferences to store in a prefs.js for a Firefox profile. Disables
    # auto updates, default browser check, etc
    prefsfile = """user_pref("app.update.auto", false);
user_pref("app.update.backgroundErrors", 1);
user_pref("app.update.enabled", false);
user_pref("app.update.lastUpdateTime.addon-background-update-timer", 0);
user_pref("app.update.lastUpdateTime.blocklist-background-update-timer", 0);
user_pref("app.update.lastUpdateTime.datareporting-healthreport-lastDailyCollection", 0);
user_pref("app.update.lastUpdateTime.experiments-update-timer", 0);
user_pref("app.update.lastUpdateTime.xpi-signature-verification", 0);
user_pref("app.update.service.enabled", false);
user_pref("browser.bookmarks.restore_default_bookmarks", false);
user_pref("browser.cache.disk.capacity", 358400);
user_pref("browser.cache.disk.filesystem_reported", 1);
user_pref("browser.cache.disk.smart_size.first_run", false);
user_pref("browser.cache.disk.smart_size.use_old_max", false);
user_pref("browser.cache.frecency_experiment", 4);
user_pref("browser.download.importedFromSqlite", true);
user_pref("browser.migration.version", 30);
user_pref("browser.newtabpage.enhanced", true);
user_pref("browser.newtabpage.introShown", true);
user_pref("browser.newtabpage.storageVersion", 1);
user_pref("browser.offline-apps.notify", false);
user_pref("browser.pagethumbnails.storage_version", 3);
user_pref("browser.places.smartBookmarksVersion", 7);
user_pref("browser.preferences.advanced.selectedTabIndex", 3);
user_pref("browser.privatebrowsing.autostart", true);
user_pref("browser.rights.3.shown", true);
user_pref("browser.safebrowsing.enabled", false);
user_pref("browser.safebrowsing.malware.enabled", false);
user_pref("browser.search.suggest.enabled", false);
user_pref("browser.search.update", false);
user_pref("browser.sessionstore.restore_on_demand", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.slowStartup.averageTime", 611);
user_pref("browser.slowStartup.samples", 2);
user_pref("browser.toolbarbuttons.introduced.pocket-button", true);
user_pref("datareporting.healthreport.service.firstRun", true);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionPolicyAcceptedVersion", 2);
user_pref("datareporting.sessions.current.activeTicks", 2);
user_pref("datareporting.sessions.current.clean", true);
user_pref("datareporting.sessions.currentIndex", 6);
user_pref("dom.apps.reset-permissions", true);
user_pref("dom.disable_open_during_load", false);
user_pref("dom.mozApps.used", true);
user_pref("experiments.activeExperiment", false);
user_pref("extensions.blocklist.pingCountVersion", 0);
user_pref("extensions.bootstrappedAddons", "{}");
user_pref("extensions.getAddons.databaseSchema", 5);
user_pref("extensions.pendingOperations", false);
user_pref("extensions.shownSelectionUI", true);
user_pref("extensions.ui.dictionary.hidden", true);
user_pref("extensions.ui.experiment.hidden", true);
user_pref("extensions.ui.lastCategory", "addons://discover/");
user_pref("extensions.ui.locale.hidden", true);
user_pref("layout.spellcheckDefault", 0);
user_pref("media.gmp-manager.buildID", "20151014143721");
user_pref("media.hardware-video-decoding.failed", false);
user_pref("network.cookie.prefsMigrated", true);
user_pref("network.predictor.cleaned-up", true);
user_pref("pdfjs.migrationVersion", 2);
user_pref("pdfjs.previousHandler.alwaysAskBeforeHandling", true);
user_pref("places.history.expiration.transient_current_max_pages", 104858);
user_pref("plugin.disable_full_page_plugin_for_types", "application/pdf");
user_pref("plugin.importedState", true);
user_pref("privacy.cpd.offlineApps", true);
user_pref("privacy.cpd.siteSettings", true);
user_pref("privacy.donottrackheader.enabled", true);
user_pref("privacy.sanitize.migrateFx3Prefs", true);
user_pref("security.OCSP.enabled", 0);
user_pref("services.sync.clients.lastSync", "0");
user_pref("services.sync.clients.lastSyncLocal", "0");
user_pref("services.sync.declinedEngines", "");
user_pref("services.sync.globalScore", 0);
user_pref("services.sync.migrated", true);
user_pref("services.sync.nextSync", 0);
user_pref("services.sync.tabs.lastSync", "0");
user_pref("services.sync.tabs.lastSyncLocal", "0");
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("xpinstall.whitelist.required", false);"""


    def start(self, target):
        firefox = self.get_path("Firefox")
        if not isinstance(target, (list, tuple)):
            target = [target]

        pids = []
        for url in target:
            profilename = random_string(8, 15)
            profile_path = os.path.join(os.getenv("TEMP"), profilename)

            subprocess.call([
                firefox,
                "-CreateProfile", "%s %s" % (profilename, profile_path)
            ])
            with open(os.path.join(profile_path, "prefs.js"), "wb") as fp:
                fp.write(self.prefsfile)

            pid = self.execute(
                firefox, args=["-no-remote", "-P", profilename, url],
                maximize=True
            )
            if pid:
                pids.append(pid)
                self.pids_targets[pid] = url

        return pids
