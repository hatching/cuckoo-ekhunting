import * as _path from 'path';
import fs from 'fs';
import chokidar from 'chokidar';
import Mustache from 'mustache';
import YAML from 'yamljs';
import pretty from 'pretty';

import { util } from './utilities';

// config extension shortcut
const pluginOptions = {
  path: null,
  file: null,
  output: null,
  partials: null,
  dataDir: null,
  wcmp: {}
};

const messages = {

  compiled: (path, file, output, targetPath, notify = false) => {

    util.talk(`${path}/${file} > ${output}${targetPath.name}.html`, {
      color: 'red',
      timestamp: false
    });

    // notify the user of succesfull html render
    if(notify)
      util.notify(`Mustache rendered (${output}${targetPath.name}.html)`);

  },

  error: (err, notify = false) => {
    console.log(err);
    if(notify)
      util.notify('Mustache: There was an error');
  }

}

// function to fetch all the partials and wrap them in a partials object
// that gets passed to mustache as a form of 'includable' entities.
let resolvePartials = partialDir => {

  let parsers = [];
  let result = {};

  let getPartial = path => new Promise((resolve, reject) => {

    let data = fs.readFileSync(path, 'utf-8');
    if(data) {
      resolve({
        name: _path.parse(path).name,
        data: data
      });
    } else {
      reject(data);
    }
  });

  return new Promise((resolve, reject) => {
    let files = fs.readdirSync(partialDir);
    files.forEach(file => parsers.push(getPartial(`${partialDir}/${file}`)));
    Promise.all(parsers).then(partials => {
      partials.forEach(partial => result[partial.name] = partial.data);
      resolve(result);
    }).catch(err => reject(err));
  });
}

let resolveData = (dataDir, helpersLocation) => {
  let set = {};
  fs.readdirSync(util.cwd(dataDir)).forEach(file => {
    let body = fs.readFileSync(`${util.cwd(dataDir)}/${file}`, 'utf-8');
    let key = _path.basename(`${util.cwd(dataDir)}/${file}`, '.yml');
    let res = YAML.parse(body);
    set[key] = res;
  });

  if(helpersLocation) {
    let exists = fs.existsSync(util.cwd(`${helpersLocation}/helpers.js`));
    if(exists) {
      const helpers = require(util.cwd(`${helpersLocation}/helpers`)).helpers;
      for(let key in helpers) set[key] = helpers[key];
    }
  }

  return set;
}

// compile
function compile(options = pluginOptions, target = false) {

  // parse config
  let {
    file,
    path,
    output,
    partials,
    dataDir,
    wcmp
  } = util.extend(pluginOptions, options);

  let templateDataset = dataDir ? resolveData(dataDir, path) : {};

  return new Promise((resolve, reject) => {
    if(target) {

      fs.readFile(target, 'utf-8',  (err, data) => {

        if(err) {
          messages.error(err, wcmp.notify);
          return reject(err);
        }

        // resolve all the available partials
        resolvePartials(partials).then(literals => {

          let html = Mustache.render(data, templateDataset, literals);
          let targetPath = _path.parse(target);
          let destination = util.cwd(`${output}${targetPath.name}.html`);

          fs.writeFile(destination, pretty(html, { ocd: true }), 'utf-8', (err, result) => {
            if(err) {
              messages.error(err, wcmp.notify);
              return reject(err);
            }

            messages.compiled(path, file, output, targetPath, wcmp.notify);
            resolve(html, `${path}/${file}`, output);
          });

        });

      });
    } else {

      let files = fs.readdirSync(path);
      if(files.length) {
        let targets = [];
        files.filter(file => _path.parse(file).ext == '.mustache').forEach(file => targets.push(compile(options, `${path}/${file}`)));
        if(targets.length) {
          Promise.all(targets).then(resolve).catch(reject);
        } else {
          messages.error('No mustache files found', wcmp.notify);
          return reject('No mustache files found');
        }
      } else {
        messages.error('No target', wcmp.notify);
        return reject('No target');
      }

    }
  });
}

// watch
function watch(options = pluginOptions) {

  // parse config
  let {
    path,
    file,
    output,
    partials
  } = util.extend(pluginOptions, options);

  let isPartial = p => p.indexOf(partials) > -1;

  // create file watcher
  return chokidar.watch([util.cwd(`${path}/${file}`), util.cwd(partials)]).on('change', _file => {
    // run the compile function for this file on each fire-action
    if(!isPartial(_file)) {
      compile(options, _file).then(msg => {
        // done!
      }).catch(err => console.log(err));
    } else {
      // it should compile all the not-partial templates.
      let comps = [];
      util.dir(util.cwd(file)).then(files => {
        files.forEach(f => comps.push(compile(options)));
      }).catch(e => console.log(e));

      Promise.all(comps).then(msg => {
        // done!
      }).catch(err => console.log(err));
    }
  });
}

export {
  compile,
  watch
}
