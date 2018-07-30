import moment from 'moment';
import Handlebars from 'handlebars';

const safe = Handlebars.SafeString;
const getLevelName = level => ['info','warning','danger'][level-1] || "";
const getIconType = level => ['fa-lightbulb','fa-exclamation-circle','fa-skull'][level-1] || "fa-comment";

// forge pwetty dates from timestamps
Handlebars.registerHelper('pretty-date', timestamp => moment(new Date(timestamp)).format('MM/DD/YYYY HH:mm:ss'));
// helper for parsing number-level to string-level
Handlebars.registerHelper('alert-level', level => getLevelName(parseInt(level)));
// spit icons from level numbers
Handlebars.registerHelper('alert-icon', level => `<i class="fal ${getIconType(level)}"></i>`);

const Templates = {

  // template for single alert entry
  event: data => Handlebars.compile(`
    <tr data-row-style="{{alert-level level}}">
      <td class="drop-padding fill-base"></td>
      <td class="centerize icon-cell">{{{alert-icon level}}}</td>
      <td class="no-wrap">{{pretty-date timestamp}}</td>
      <td>{{title}}</td>
      <td class="text-wrap">{{content}}</td>
      <td class="no-wrap">
        {{#if targetgroup_name}}
          {{targetgroup_name}}
        {{else}}
          <em class="secundary">Unspecified</em>
        {{/if}}
      </td>
      <td class="icon-cell"><a href="#" data-expand-row><i class="fal"></i></a></td>
    </tr>
    <tr class="info-expansion">
      <td colspan="7">
        <ul class="meta-summary">
          <li>
            <i class="far fa-barcode-alt"></i>
            {{#if targetgroup_name}}
              {{targetgroup_name}}
            {{else}}
              <em class="secundary">Unspecified</em>
            {{/if}}
          </li>
          <li>
            <i class="far fa-clock"></i>
            {{pretty-date timestamp}}
          </li>
        </ul>
        <h3>{{title}}</h3>
        <p>{{content}}</p>
        <a href="{{target}}" target="_blank" class="button"><i class="far fa-file-alt"></i> View report</a>
      </td>
    </tr>
  `)(data),

  // definition for url group
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

  // definition for a table-error
  ajaxError: data => Handlebars.compile(`
    <tr class="error-row">
      <td colspan="{{span}}">
        <p>{{message}} <button type="button" data-dismiss><i class="fas fa-times"></i></button></p>
      </td>
    </tr>
  `)(data)

};

export default Templates;
