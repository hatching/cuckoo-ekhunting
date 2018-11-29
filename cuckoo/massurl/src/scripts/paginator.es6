import $ from 'jquery';
import EventEmitter  from './event-emitter';

export default class Paginator extends EventEmitter {

  constructor(props={}) {

    super();

    this.props = {
      url: null,
      limit: 0,
      offset: 0,
      ...props
    }

    this.events = {
      request: [],
      payload: [],
      error: []
    }

  }

  // makes a request
  request() {
    let { url, current, limit, offset } = this.props;
    return new Promise((resolve, reject) => {
      $.get(
        this.url,
        response => {
          resolve(response);
          this.increment();
        },
        error => {
          reject(error);
          this.emit('error', error);
        }, "json"
      );
    });
  }

  next() {
    this.props.offset += 1;
    let { offset, limit } = this.props;
    this.request().then(response => {
      this.emit('payload', { offset, response });
    }).catch(err => this.emit('error', err));
  }

  increment() { this.props.current += 1; }

  get current() { return this.props.current; }
  get limit()   { return this.props.limit; }
  get offset()  { return this.props.offset; }
  get url()     { return `${this.props.url}?offset=${this.offset}&limit=${this.limit}`; }

}
