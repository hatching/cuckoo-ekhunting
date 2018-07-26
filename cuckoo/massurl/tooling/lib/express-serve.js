import path from 'path';
import express from 'express';
import FancyLogger from './fancy-logger';
import { util } from './utilities';

// create logger
const logger = new FancyLogger();
const messages = {
  warn: warning => warning.message ? logger.warn(warning.message) : console.log(warning)
}

// configuration object
let createConfig = (options = {}) => util.createConfig({
  enabled: true,
  port: 3000,
  root: 'dist/*.html',
  static: 'dist/'
}, options);

// Server (express) code
export default function Server(api) {

  let config = createConfig(api);

  if(!config.root) {
    messages.warn('WCMP.server needs a root! Validate your configuration and try again.');
    return false;
  }

  return new Promise((resolve, reject) => {
    // get contents of the root dir
    util.dir(config.root).then(files => {
      // strip down to a subset of only html
      const app = express();
      const router = express.Router();

      app.use(express.static(config.static));

      files.forEach(file => {
        let name = path.basename(file.replace(/\.[^/.]+$/, ""));
        router.get(`/${name}`, (req, res) => {
          res.sendFile(util.cwd(file));
        });
      });

      app.use(router);
      app.listen(config.port);
      resolve(app);

    }).catch(err => logger.warn(err.message || err));
  });

}
