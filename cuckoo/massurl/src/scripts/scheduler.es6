// https://flatpickr.js.org
import flatpickr from 'flatpickr';

// define any renderable HTML for the core
const Templates = {
  Overlay: (values={}) => `
    <div class="scheduler--parent">
      <form class="scheduler--dialog">
        <div class="scheduler__frequency">
          <select class="scheduler--input-control" name="frequency" value="${values.frequency}">
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="yearly">Yearly</option>
          </select>
          <i class="fas fa-caret-down caret"></i>
        </div>
        <div class="scheduler__date" data-display="monthly, yearly">
          <label class="scheduler__label">from date</label>
          <div>
            <input
              type="text"
              value="${values.date}"
              class="scheduler--input-control"
              name="date"
              placeholder="date"
              data-flatpickr />
            <i class="fas fa-caret-down caret"></i>
          </div>
        </div>
        <div class="scheduler__days" data-display="weekly">
          <label class="scheduler__label" for="sc-pick-day">day</label>
          <select name="day" value="${values.day}">
            <option value="mondays">Mondays</option>
            <option value="tuesdays">Tuesdays</option>
            <option value="wednesdays">Wednesdays</option>
            <option value="thursdays">Thursdays</option>
            <option value="fridays">Fridays</option>
            <option value="saturdays">Saturdays</option>
            <option value="sundays">Sundays</option>
          </select>
          <i class="fas fa-caret-down caret"></i>
        </div>
        <div class="scheduler__time">
          <div data-range="00:23">
            <a href="range:up"><i class="fal fa-angle-up"></i></a>
            <input class="scheduler--input-control" value="${values.time.hours}" />
            <a href="range:down"><i class="fal fa-angle-down"></i></a>
          </div>
          <span>:</span>
          <div data-range="00:59">
            <a href="range:up"><i class="fal fa-angle-up"></i></a>
            <input class="scheduler--input-control" value="${values.time.minutes}" />
            <a href="range:down"><i class="fal fa-angle-down"></i></a>
          </div>
        </div>
        <nav class="scheduler__control">
          <div>
            <button class="button" data-control="submit"><i class="fas fa-check"></i></button>
          </div>
          <div class="meta-controls">
            <button title="Close scheduler" data-control="close"><i class="far fa-times"></i></button>
            <button title="Reset scheduler" data-control="reset"><i class="fas fa-trash"></i></button>
          </div>
        </nav>
      </form>
    </div>`
};

// small helper utility
const helpers = {
  // leading zero (Number,Size(many zeroes)) - returns N as string
  lz: (n=0,s=1) => {
    let ns = ""+n;
    return ns.length < s ? "0"+ns : ns;
  },
  // parses date string from JS Date > "YYYY-mm-dd"
  dateToString: d => [
    d.getFullYear(),
    helpers.lz(d.getMonth()+1, 2),
    helpers.lz(d.getDate(), 2)
  ].join('-')
};

// micro-UI controls
const lib = {
  /*
    'up-and-down' range picker
   */
  RangePick: function(el, props={}) {
    let input = el.querySelector('input');
    // parse range min and max from data string
    let range = (function(s="") {
      return {
        cur: 0,
        min: parseInt(s.split(':')[0]),
        max: parseInt(s.split(':')[1])
      };
    }(el.dataset.range || "0:10"));
    // UI handlers
    let handlers = {
      set: v => {
        range.cur   = v;
        input.value = helpers.lz(v,2);
      },
      up: () => {
        if(range.cur+1 > range.max)
          range.cur = range.min;
        else
          range.cur += 1;
        handlers.set(range.cur);
      },
      down: () => {
        if(range.cur-1 > range.min)
          range.cur = range.cur-1;
        else
          range.cur = range.max;
        handlers.set(range.cur);
      }
    };
    // bind handlers
    el.querySelectorAll('[href^="range:"]').forEach(e => {
      let act = e.getAttribute('href').split(':')[1];
      e.addEventListener('click', ev => {
        ev.preventDefault();
        handlers[act]();
      });
    });
    // handle typing in input field
    input.addEventListener('keyup', ev => {
      ev.preventDefault();
      let v = parseInt(input.value);
      let inRange = n => (n <= range.max) && (n >= range.min);
      switch(ev.key) {
        case 'ArrowUp':
          handlers.up();
        break;
        case 'ArrowDown':
          handlers.down();
        break;
        default:
          if(!isNaN(v) && inRange(v))
            handlers.set(v);
          else
            handlers.set(range.min);
      }
    });
    // initialize with existing value
    if(input.value)
      handlers.set(parseInt(input.value));
    // return stuff
    return { range };
  }
}

/*
  Smart scheduler UI widget
 */
function VALUES(v) {
 let r = {};
 // return default set of values if value is not set
  if(!v) {
    return {
     frequency: 'weekly',
     date: helpers.dateToString(new Date()),
     day: 'mondays',
     time: {
       hours: new Date().getHours(),
       minutes: new Date().getMinutes()
     }
    };
  } else {
   // format values to a proper value format
    return VALUES(false);
  }
};

export default class Scheduler {

  // constructs the class
  constructor(props={}) {

    this.props = {
      button: null,
      open: false,
      value: false,
      submit: false,
      ...props
    };

    this.values = VALUES(this.props.values);

    this.events = {
      frequency: []
    };

    this.dialog = null;
    this.flatpickr = null;

    this.init();
  }

  // binds the UI
  init() {

    // attach 'toggle' to element this class has been constructed on
    if(this.props.button instanceof HTMLElement)
      this.props.button.addEventListener('click', e => this.toggle());

    // if the dialog is opened, close it using ESC
    window.addEventListener('keyup', e => {
      switch(e.key) {
        case 'Escape':
          if(this.open)
            this.toggle();
        break;
      }
    });

  }

  // toggles the scheduler window
  toggle() {
    if(this.open) {
      if(this.dialog)
        this.parent.removeChild(this.dialog);
      this.unbind();
      this.open = false;
    } else {
      this.parent.appendChild(this.render());
      this.bind();
      this.open = true;
    }

    this.props.button.classList.toggle('pressed', this.open);
  }

  // renders the dialog into the parent container
  render() {
    let parser = new DOMParser();
    // formats keys to specific values
    let formatKeys = o => Object.assign(o,{});
    let html = parser.parseFromString(Templates.Overlay(formatKeys(this.values)), 'text/html');
    this.dialog = html.body.firstChild;
    return this.dialog;
  }

  // attach events and other UI manipulations after render
  bind() {
    const form = this.dialog.querySelector('form');
    const close = this.dialog.querySelector('[data-control="close"]');
    const reset = this.dialog.querySelector('[data-control="reset"]');
    const submit = this.dialog.querySelector('[data-control="submit"]');
    const date  = this.dialog.querySelector('[data-flatpickr]');
    const range = this.dialog.querySelectorAll('[data-range]');
    const freq = this.dialog.querySelector('select[name="frequency"]');
    // prevDefault form
    form.addEventListener('submit', e => e.preventDefault());
    // bind submit button
    submit.addEventListener('click', () => this.submit());
    // bind close button
    close.addEventListener('click', () => this.toggle());
    // bind reset button
    reset.addEventListener('click', () => this.reset());
    // initialize flatpickr
    if(date !== null)
      this.flatpickr = flatpickr(date, {
        defaultDate: this.values.date,
        format: 'Y-m-d'
      });
    // initialize timepicker
    range.forEach(r => {
      lib.RangePick(r,this.values.time);
    });
    // toggles elements on and off based on frequency input
    let toggleElements = f => {
      this.dialog.querySelectorAll('[data-display]').forEach(el => {
        let display = (el.dataset.display.indexOf(freq.value) == -1);
        el.classList.toggle('hidden',display);
      });
    }
    // display the correct fields per frequency setting
    freq.addEventListener('change', e => toggleElements(freq.value));
    // trigger once on init
    freq.dispatchEvent(new Event('change'));
  }

  // destroys stuff that belongs to this instance
  unbind() {
    if(this.flatpickr)
      this.flatpickr.destroy();
  }

  // resets the scheduler data
  reset() {
    let confirmed = confirm('Reset the current schedule? This cannot be undone.');
    if(confirmed) {
      this.toggle();
      if(this.props.reset instanceof Function)
        this.props.reset(this);
    }
  }

  // collects all data
  submit() {
    this.toggle();
    if(this.props.submit instanceof Function)
      this.props.submit(this.values);
  }

  // subscribes callbacks to stack
  on(e, cb) {
    if(e.indexOf(' ') > -1) {
      // subscribe space-separated events iterative
      // (calls .on for each result on e splitted by spaces)
      e = e.split(' ').forEach(ev => this.on(ev, cb));
    } else {
      if(this.events[e]) {
        this.events[e].push(cb);
      } else {
        this.events[e] = [cb];
      }
    }
    return this;
  }

  // emits callback stack
  emit(e,d={},any=false) {
    if(this.events[e]) {
      this.events[e].forEach(cb => {
        cb.call(this, d);
      });
    }
    if(!any) this.emit('*',e,true);
    return this;
  }

  get open() { return this.props.open; }
  set open(o) { this.props.open = o; }
  get parent() { return this.props.button.parentNode; }

}
