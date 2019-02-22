import moment from 'moment';
import Handlebars from 'handlebars';

const safe = Handlebars.SafeString;
const getLevelName = level => ['info','warning','danger'][level-1] || "";
const getIconType = level => ['fa-lightbulb','fa-exclamation-circle','fa-skull'][level-1] || "fa-comment";

// parse a timestamp to a unix format
Handlebars.registerHelper('unix-time', timestamp => moment(timestamp).unix());
// forge pwetty dates from timestamps
Handlebars.registerHelper('pretty-date', timestamp => moment(timestamp).format('MM/DD/YYYY HH:mm:ss'));
// helper for parsing number-level to string-level
Handlebars.registerHelper('alert-level', level => getLevelName(parseInt(level)));
// spit icons from level numbers
Handlebars.registerHelper('alert-icon', level => `<i class="fal ${getIconType(level)}"></i>`);
// generate a shortened version of a big string
Handlebars.registerHelper('truncate', content => (content.length > 70) ? content.substr(0, 70-1) + '&hellip;' : content);
// handlebars inline join helper
Handlebars.registerHelper('join', arr => arr.join('\n'));
// returns a status icon based on process status
Handlebars.registerHelper('status-icon', status => {
  switch(status) {
    case 'pending':
      return '<i class="far fa-hourglass"></i>';
    break;
    case 'running':
      return '<i class="far fa-spinner-third fa-spin"></i>';
    break;
    case 'completed':
      return '<i class="far fa-check"></i>';
    break;
  }
});

const Templates = {

  // template for a top-level alert
  topEvent: data => Handlebars.compile(`
    <div class="alert alert-{{alert-level level}}">
      <div class="alert-icon">
        <figure>{{{alert-icon level}}}</figure>
      </div>
      <div class="alert-content">
        <h2>{{title}}</h2>
        <p>{{{truncate content}}}</p>
        <a class="button" href="#">Show info</a>
      </div>
      <div class="alert-time">
        {{#if url_group_name}}
          <p>{{url_group_name}}</p>
        {{/if}}
        <p>{{timestamp}}</p>
      </div>
    </div>
    <div class="alert-loader">
      <!-- <div class="alert-loader-inner"></div> -->
    </div>
  `)(data),

  // template for single alert entry
  event: data => Handlebars.compile(`
    <tr data-row-style="{{alert-level level}}" data-id="{{id}}">
      <td class="drop-padding {{#unless read}}fill-base{{/unless}}"></td>
      <td class="centerize icon-cell" data-sort-number="{{level}}">{{{alert-icon level}}}</td>
      <td class="no-wrap" data-sort-number="{{unix-time timestamp}}">{{timestamp}}</td>
      <td>{{title}}</td>
      <td class="text-wrap">{{content}}</td>
      <td class="no-wrap">
        {{#if url_group_name}}
          <a class="follow-link" href="/url-groups/view?v={{url_group_name}}">{{url_group_name}} <i></i></a>
        {{else}}
          <em class="secundary">No group</em>
        {{/if}}
      </td>
      <td class="icon-cell"><a href="#" data-expand-row><i class="fal"></i></a></td>
    </tr>
  `)(data),

  // info row to display more alert info
  eventInfo: data => Handlebars.compile(`
    <tr class="info-expansion" data-belongs-to="{{task_id}}">
      <td colspan="7">
        <ul class="meta-summary">
          {{#if url_group_name}}
          <li>
            <i class="far fa-barcode-alt"></i>
            {{url_group_name}}
          </li>
          {{/if}}
          <li>
            <i class="far fa-clock"></i>
            {{timestamp}}
          </li>
        </ul>
        <h3>{{title}}</h3>
        <p>{{content}}</p>
        {{#if diary_id}}
          <a href="/diary/{{diary_id}}" class="button"><i class="far fa-book"></i> Show diary</a>
        {{/if}}
        {{#if task_id}}
          <a href="/api/pcap/{{task_id}}" class="button">
            <i class="far fa-file-alt"></i> Download PCAP
          </a>
        {{/if}}
      </td>
    </tr>
  `)(data),

  // template for url group
  urlGroup: data => Handlebars.compile(`
    <tr data-group-id="{{id}}">
      <td class="centerize">{{id}}</td>
      <td>{{name}}</td>
      <td>{{description}}</td>
      <td class="centerize">
        <button type="button" class="button icon-button" data-edit>
          <i class="far fa-marker"></i>
        </button>
        <button type="button" class="button icon-button" data-remove>
          <i class="far fa-times"></i>
        </button>
      </td>
    </tr>
  `)(data),

  // template for a table-error
  ajaxError: data => Handlebars.compile(`
    <tr class="error-row">
      <td colspan="{{span}}">
        <p>{{message}} <button type="button" data-dismiss><i class="fas fa-times"></i></button></p>
      </td>
    </tr>
  `)(data),

  // template for url-editor
  editor: data => Handlebars.compile(`
    <header>
      <div>
        <h3>{{{status-icon status}}} {{name}}</h3>
        <p>{{description}}</p>
      </div>
      <nav>
        <button class="button icon-button" data-schedule-now>Scan now</button>
        <p>or</p>
        <div>
          <button class="button icon-button" data-schedule="{{id}}" id="toggle-scheduler"><i class="fal fa-calendar{{#if schedule}}-check{{/if}}"></i> <span>Schedule{{#if schedule}}d at {{schedule_next}}{{/if}}</span></button>
        </div>
        <button class="button icon-button" data-save="{{id}}"><i class="fal fa-save"></i> Save</button>
        <button class="button icon-button" data-close><i class="fal fa-times"></i></button>
      </nav>
    </header>
    <hr />
    <div class="url-area">
      <textarea placeholder="Type urls here">{{join urls}}</textarea>
    </div>
  `)(data),

  // constructs an overlay and dumps a huge amount of content in it. Spreads
  // over the entire page
  requestView: data => Handlebars.compile(`
    <div class="content-overlay">
      <nav class="content-overlay__navbar">
        <a href="#" class="close-dialog" title="Close view"><i class="fal fa-times"></i></a>
      </nav>
      <div class="content-overlay__dialog">
        {{#each this}}
          <p>{{pretty-date time}}</p>
          <div class="network-body">
            <div>
              <h4>Request</h4>
              <textarea disabled>{{request}}</textarea>
            </div>
            <div>
              <h4>Response</h4>
              <textarea disabled>{{response}}</textarea>
            </div>
          </div>
        {{/each}}
      </div>
    </div>
  `)(data)

};

export default Templates;
