import fs from 'fs';
import path from 'path';
import notifier from 'node-notifier';
import FancyLogger from './fancy-logger';

const glob = require('glob-fs')({});
const logger = new FancyLogger();

class Utilities {

  // easy cwd mapping
  static cwd(file) {
    let dir = path.dirname(require.main.filename);
    return `${dir}/${file}`;
  }

  // mapping to a dependency in node_modules
  static dep(pkgPath = '/node_modules') {
    return Utilities.cwd(`node_modules/${pkgPath}`);
  }

  // quickly retrieve the extension name of a path
  static extension(url = undefined) {
    if(!url) return false;
    return path.extname(url);
  }

  // writeBuffer shortcut as a promise
  static writeBuffer(output, buffer) {
    return new Promise((resolve, reject) => {
      fs.writeFile(output, buffer, err => {
        if(err) {
          reject(err);
          return;
        }
        resolve({ output, buffer });
      })
    });
  }

  // utility for stripping out ugly '../' parts from paths.
  static prettyPath(pathString) {
    return pathString.split('/').filter(part => part.indexOf('..') == -1).join('/');
  }

  // returns if package has been called as a module or not
  // > says it's not by default. Make sure that the require object
  //   is passed as a param.
  static wasRequired(_req = undefined) {
    let isCLI = _req.main === module;
    return !isCLI;
  }

  // shortcut for smart object extending, set of defaults versus object
  // returns a new object constructed from the default input set and then
  // matched against the input object.
  static extend(defaults = {}, input = {}) {
    return Object.assign(defaults, input);
  }

  // print out a message with fancylogger
  static talk(msg, options) {
    logger.frame(msg, options);
  }

  // pushes a native notification to the client
  static notify(message = '') {
    notifier.notify({
      title: 'WCMP',
      icon: Utilities.cwd(`tooling/resources/wcmp-icon.png`),
      message
    });
  }

  // shortcut to 'createConfig'
  static createConfig(defaults = {}, config = {}) {
    return Object.assign(defaults, config);
  }

  // get a directory iteraterable (=Promise)
  static dir(d) {
    return new Promise((resolve, reject) => {
      glob.readdir(d, (e, f) => {
        if(e)
          reject({e,message:'util.readdir failed'});
        resolve(f);
      });
    });
  }

}

export { Utilities as util };
