const fs        = require('fs');
const extend    = require('deep-extend');
const parseArgs = require('minimist');

let _cmd = parseArgs(process.argv, {});

let singleRun = (
  _cmd.scripts
  || _cmd.styles
  || _cmd.build
  || _cmd.html
  || _cmd.serve
) == true;

let wasRequired = !(require.main === module);
let isBuiltLegacy = fs.existsSync('./tooling/build');
let forceBabel = _cmd['force-babel'] === true;
let tooling;

// formatting the config from json to a default set of config
// ensures that the system won't fail on missing configuration
// keys. If you add features, make sure to add the options to the
// default stack along any other modifications to that content
// if neccesary.
const CONFIG_JSON = JSON.parse(fs.readFileSync('./config.json', 'utf-8'));

//
// default configuration
//
const CONFIG_DEFAULT = {
  "babel": {
    "path": "src/scripts",
    "file": "index.es6",
    "output": "/build/main.js",
    "browserify": {},
    "babel": {},
    "wcmp": {
      "notify": false
    }
  },
  "sass": {
    "path": "src/styles",
    "file": "main.scss",
    "output": "build/css/styles.css",
    "sass": {},
    "wcmp": {
      "notify": false
    }
  },
  "html": {
    "path": "src/html",
    "file": "*.html",
    "output": "build/",
    "partials": "src/html/partials",
    "dataDir": null,
    "wcmp": {
      "notify": false
    }
  },
  "server": {
    "enabled": true,
    "port": 3000,
    "root": "dist/*.html",
    "static": "dist/"
  }
}

//
// result configuration after extending the json onto the option stack.
// CONFIG is globally accesible by all modules.
//
const CONFIG = extend(CONFIG_DEFAULT, CONFIG_JSON);

// if imported as a module, skip to the bottom
if(!wasRequired) {
  if(isBuiltLegacy && !forceBabel) {
    // source code has been built => $ npm build
    tooling = require(__dirname + '/tooling/build');
  } else {
    // source code has not been built - use babel-node to run.
    require('babel-register');
    tooling = require(__dirname + '/tooling');
  }
}

if(wasRequired) {

  // expose some tech from package
  module.exports = tooling;

} else {

  if(!singleRun) {

    tooling.start({
      config: CONFIG,
      development_mode: _cmd.development
    });

  } else {

    if(_cmd.styles) {
      tooling.compileStyles(CONFIG.sass).catch(function(e) {
        // console.log(e);
      });
    }
    if(_cmd.scripts) {
      tooling.compileScripts(CONFIG.babel).catch(function(e) {
        // console.log(e);
      });
    }
    if(_cmd.html) {
      tooling.compileHTML(CONFIG.html).catch(function(e) {
        // console.log(e);
      });
    }
    if(_cmd.serve) {
      const serve = tooling.Server(CONFIG.server).then(app => {
        tooling.util.talk(`App served at port ${CONFIG.server.port}`);
      }).catch(e => console.log(e));
    }
    if(_cmd.build) {
      Promise.all([
        tooling.compileScripts(CONFIG.babel),
        tooling.compileStyles(CONFIG.sass),
        tooling.compileHTML(CONFIG.html)
      ]).catch(err => console.log(err));
    }

  }

}
