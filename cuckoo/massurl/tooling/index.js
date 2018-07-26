import {
  watch as watchStyles,
  compile as compileStyles
} from './lib/frontend-styles';

import {
  watch as watchScripts,
  transpile as compileScripts
} from './lib/frontend-scripts';

import {
  watch as watchHTML,
  compile as compileHTML
} from './lib/frontend-html';

import Server from './lib/express-serve';

import { util } from './lib/utilities';

/* =============
  Tooling.welcomeMessage
  - shows a friendly welcome message to
============= */
function welcomeMessage(devMode = false) {

  let message = `watchers started - happy coding!`;

  if(devMode === true) message = `Running development mode and ${message}`;

  util.talk(message, {
    color: 'white',
    timestamp: false
  });

}

/* =============
Tooling.start
  - starts the watchers for sass and babel files
============= */
function start(api) {
  const sassWatcher = watchStyles(api.config.sass);
  const scriptsWatcher = watchScripts(api.config.babel);
  const htmlWatcher = watchHTML(api.config.html);

  if(api.config.server.enabled) {
    const serve = Server(api.config.server);
    serve.then(app => {
      util.talk(`App served at port ${api.config.server.port}`);
    }).catch(e => console.log(e));
  }

  welcomeMessage(api.development_mode);
}

export {
  start,
  watchStyles,
  watchScripts,
  watchHTML,
  compileStyles,
  compileScripts,
  compileHTML,
  Server,
  util
}
