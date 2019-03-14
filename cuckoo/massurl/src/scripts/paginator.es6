import $ from 'jquery';
import EventEmitter  from './event-emitter';

export default class Paginator extends EventEmitter {

  constructor(props={}) {

    super();

    this.props = {
      url: null,
      limit: 0,
      offset: 0,
      autoIncrement: true,
      startChar: '?',
      ...props
    }

    this.events = {
      request: [],
      payload: [],
      error: [],
      empty: []
    }

  }

  // makes a request
  request() {
    let { url, limit, offset } = this.props;
    return new Promise((resolve, reject) => {
      $.get(
        this.url,
        response => {
          resolve(response);
        },
        error => {
          reject(error);
          this.emit('error', error);
        }, "json"
      );
    });
  }

  next() {
    let { offset, limit } = this.props;
    if(this.props.autoIncrement)
      this.increment();
    this.request().then(response => {
      if(response.length > 0)
        this.emit('payload', { offset, response });
      else
        this.emit('empty', {});
    }).catch(err => this.emit('error', err));
  }

  increment() { this.props.offset += 1; }

  get limit()   { return this.props.limit; }
  get offset()  { return this.props.offset; }
  get url()     {
    let encoded = encodeURIComponent(`${this.props.startChar}offset=${this.offset}&limit=${this.limit}`)
    return `${this.props.url}${encoded}`; 
  }

  set offset(v) { this.props.offset = v; }

}
