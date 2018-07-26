import fs from 'fs';
import path from 'path';
import browserify from 'browserify';
import exorcist from 'exorcist';
import chokidar from 'chokidar';

import FancyLogger from './fancy-logger';
import { util } from './utilities';

// create logger
const logger = new FancyLogger();

let messages = {
  compiled: (path, file, output, notify = false) => {
    logger.frame(`${path}/${file} > ${output}`, {
      color: 'yellow'
    });

    if(notify)
      util.notify(`Babel transpiled > ${output}`);
  },
  error: (err, notify = false) => {
    if(err instanceof Object) {
      console.log(err.codeFrame);
      console.log(err.message);
    } else {
      console.log(err);
    }
    if(notify)
      util.notify('Babel: There was an error.');
  }
}

// config creation shortcut
let createConfig = (options = {}) => Object.assign({
  path: null,
  file: null,
  output: null,
  wcmp: {}
}, options);

/*
  does a transpilation of a single entry file
 */
function transpile(options = {}) {

  // parse config
  let {
    path,
    file,
    output,
    wcmp
  } = createConfig(options);

  // extract the babel/browserify options
  let _babel = options.babel || {};
  let _browserify = options.browserify || {};

  if(_babel.extensions) _browserify.extensions = _babel.extensions;

  return new Promise((resolve, reject) => {

    let b = browserify(util.cwd(`${path}/${file}`), _browserify);

    b.transform("babelify", _babel);

    b.on('bundle', function(bundle) {
      // resolve('Script transpiling done');
    });

    let didError = false;

    b.bundle()
      .on('error', function(err) {
        didError = true;
        messages.error(err, wcmp.notify);
        this.emit('end');
        reject(err);
      })
      .on('end', function(bundle) {
        if(!didError) messages.compiled(path, file, output, wcmp.notify);
        resolve('Script transpiling done');
      })
      .pipe(exorcist(util.cwd(`${output}.map`)))
      .pipe(fs.createWriteStream(util.cwd(output)));

  });

}

/*
  starts a watcher that will call transpile on file changes.
 */
function watch(options = {}) {

  // parse config
  let {
    path,
    file,
    output
  } = createConfig(options);

  return chokidar.watch(util.cwd(path)).on('change', (event, p) => {
    transpile(options).then(result => {
      // cycle done
    }, err => {
      console.log(err);
    })
  });

}

export { transpile, watch }
