import chalk from 'chalk';
import moment from 'moment';

// creates a row of '=' matching the strings width
let Row = (msg, char = '-') => {
  let row = '';
  for(let i = 0; i < msg.length-10; i++) {
    row += char;
  }
  return row;
}

let TimeStamp = () => {
  let m = moment(new Date());
  return m.format('MM-DD-YYYY HH:mm:ss');
}

class FancyLogger {

  /*
    1-line frame log:
    ===============
    = hello world =
    ===============
  */
  frame(msg, options = {}) {

    let opts = Object.assign({
      char: '=',
      timestamp: true
    }, options);

    if(opts.timestamp) {
      msg = `[${TimeStamp()}] ${msg}`;
    }

    let base = `¦ ${chalk.white(msg)} ¦`;
    let str = `${Row(base,opts.char)}\n${base}\n${Row(base,opts.char)}`;
    this.draw(str, options);

  }

  draw(str, options) {

    let opts = Object.assign({
      type: false,
      color: false
    }, options);

    let colorFn;

    // must be a 'chalk' color
    if(opts.color) {
      colorFn = chalk[opts.color];
    }

    if(opts.type) {
      switch(opts.type) {
        case 'error':
          colorFn = chalk.red;
        break;
        case 'success':
          colorFn = chalk.green;
        break;
        case 'info':
          colorFn = chalk.blue;
        break;
        default:
          colorFn = chalk.white;
        break;
      }
    }

    if(colorFn) {
      console.log(colorFn(str));
    } else {
      console.log(str);
    }

  }

}

export default FancyLogger;
