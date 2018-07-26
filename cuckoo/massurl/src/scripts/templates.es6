import moment from 'moment';
import Handlebars from 'handlebars';

const safe = Handlebars.SafeString;
const getLevelName = level => ['info','warning','danger'][level-1] || "";
const getIconType = level => ['fa-lightbulb','fa-exclamation-triangle','fa-skull'][level-1] || "fa-comment";

// forge pwetty dates from timestamps
Handlebars.registerHelper('pretty-date', timestamp => safe(moment(new Date(timestamp)).format('MM/DD/YYYY HH:mm:ss')));
// helper for parsing number-level to string-level
Handlebars.registerHelper('alert-level', level => safe(getLevelName(parseInt(level))));
// spit icons from level numbers
Handlebars.registerHelper('alert-icon', level => `<i class="fal ${getIconType(level)}"></i>`);

const Templates = {

  // template for single alert entry
  event: data => Handlebars.compile(`
    <tr data-row-style="{{alert-level level}}">
      <td class="drop-padding fill-base"></td>
      <td class="centerize icon-cell">{{alert-icon level}}</td>
      <td class="no-wrap">{{pretty-date timestamp}}</td>
      <td class="no-wrap">{{target_group.name}}</td>
      <td>{{title}}</td>
      <td class="text-wrap">{{content}}</td>
      <td class="icon-cell"><a href="#" data-expand-row><i class="fal"></i></a></td>
    </tr>
    <tr class="info-expansion">
      <td colspan="7">
        <ul class="meta-summary">
          <li><i class="far fa-barcode-alt"></i> {{target_group.name}}</li>
          <li>
            <i class="far fa-clock"></i>
            {{pretty-date timestamp}}
          </li>
        </ul>
        <h3>{{title}}</h3>
        <p>{{content}}</p>
        <a href="{{analysis_url}}" class="button"><i class="far fa-file-alt"></i> View report</a>
      </td>
    </tr>
  `)(data),
  // definition for url group
  urlGroup: data => Handlebars.compile(`
    <tr>
      <td class="centerize">{{id}}</td>
      <td>{{name}}</td>
      <td>{{description}}</td>
      <td class="centerize">
        <button class="button icon-button">
          <i class="far fa-marker"></i>
        </button>
        <button class="button icon-button">
          <i class="far fa-times"></i>
        </button>
      </td>
    </tr>
  `)(data)
};

export default Templates;
