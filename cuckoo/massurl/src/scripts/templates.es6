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
      return `<i class="far fa-hourglass" title="${status}"></i>`;
    break;
    case 'running':
      return `<i class="far fa-spinner-third fa-spin" title="${status}"></i>`;
    break;
    case 'completed':
      return `<i class="far fa-check" title="${status}"></i>`;
    break;
  }
});
// checks if a group has not status or is completed
Handlebars.registerHelper('can-schedule', (group, opts) => {
  let canSchedule = true;
  if(group.status == "pending" || group.status == "running") canSchedule = false;
  if(group.profiles.length == 0) canSchedule = false;
  if(group.urls.length == 0) canSchedule = false;
  if(!canSchedule) return 'disabled';
});
// checks if a profile has already been selected
Handlebars.registerHelper('didSelectProfile', (pid,sid,o) => (sid.map(p=>p.id).indexOf(pid) > -1) ? o.fn() : '');

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
    <tr data-group-id="{{id}}" data-group-name="{{name}}" data-filter-value="{{name}}">
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

  // renders a list entry for the group list view
  groupListItem: data => Handlebars.compile(`
    <li data-id="{{id}}" data-name="{{name}}" data-filter-value="{{name}}">
      <a href="open:{{id}}">
        {{name}} <em class="url-count">{{urlcount}}</em>
        {{#if schedule_next}}
          <span><i class="fal fa-calendar-check"></i> {{schedule_next}}</span>
        {{/if}}
        <div title="View alerts" class="events-badge {{#if highalert}}has-critical{{/if}}">{{unread}}</div>
      </a>
    </li>
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
        <button class="button icon-button" data-schedule-now {{{can-schedule this}}}>Scan now</button>
        <p>or</p>
        <div>
          <button class="button icon-button" data-schedule="{{id}}" id="toggle-scheduler" {{{can-schedule this}}}><i class="fal fa-calendar{{#if schedule}}-check{{/if}}"></i> <span>Schedule{{#if schedule}}d at {{schedule_next}}{{/if}}</span></button>
        </div>
        <button class="button icon-button" data-save="{{id}}"><i class="fal fa-save"></i> Save</button>
        <button class="button icon-button" data-settings><i class="fas fa-ellipsis-v"></i></button>
        <button class="button icon-button" data-close><i class="fal fa-times"></i></button>
      </nav>
    </header>
    <hr />
    <div class="url-area">
      <textarea placeholder="Type urls here">{{join urls}}</textarea>
    </div>
  `)(data),

  groupSettings: data => Handlebars.compile(`
    <div class="editor-settings configure">
      <header>
        <h4>Settings</h4>
        <a data-close href="#" title="Close dialog"><i class="far fa-times"></i></a>
      </header>
      <section>
        <div class="configure-block">
          <h4 class="configure-block__label">Profiles</h4>
          <p class="configure-block__description">Analyses within this group are processed with the profiles listed underneath. Select the profiles this group has to use during analysis.</p>
        </div>
        <div class="multi-select blue" id="select-profiles">
          <ul>
            {{#each profiles}}
              <li>
                <input type="checkbox" id="profile-{{id}}" name="profile" value="{{id}}" {{#didSelectProfile id ../group.profiles}}checked{{/didSelectProfile}} />
                <label for="profile-{{id}}">{{name}}</label>
              </li>
            {{/each}}
          </ul>
        </div>
        <div class="configure-block flex">
          <a href="/settings/profiles"><small>Edit profiles</small></a>
          <div>
            <button class="button" id="save-group-profiles">Set profiles</button>
          </div>
        </div>
        <div class="configure-block">
          <h4 class="configure-block__label">Threshold</h4>
          <p class="configure-block__description">The amount of URLs per created task when analyzing a group.</p>
          <div class="configure-block__control--wrapper inline">
            <input type="text" value="{{group.max_parallel}}" class="configure-block__control mini" name="group-threshold" />
            <p class="configure-block__description">URLs</p>
          </div>
        </div>
        <div class="configure-block">
          <h4 class="configure-block__label">Batch size</h4>
          <p class="configure-block__description">The amount of URLs opened at the same time inside of a VM</p>
          <div class="configure-block__control--wrapper inline">
            <input type="text" value="{{group.batch_size}}" class="configure-block__control mini" name="batch-size" />
            <p class="configure-block__description">URLs</p>
          </div>
        </div>
        <div class="configure-block">
          <h4 class="configure-block__label">Batch timeout</h4>
          <p class="configure-block__description">The amount of seconds the URLs batch remains opened before the next batch is opened.</p>
          <div class="configure-block__control--wrapper inline">
            <input type="text" value="{{group.batch_time}}" class="configure-block__control mini" name="batch-time" />
            <p class="configure-block__description">Seconds</p>
          </div>
        </div>
        <div class="configure-block flex">
          <div>
            <button class="button" id="save-group-settings">Save settings</button>
          </div>
        </div>
      </section>
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
        {{#each log}}
          <p>
            <small>{{../url}}</small>
            {{pretty-date time}}
          </p>
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
  `)(data),

};

export default Templates;
