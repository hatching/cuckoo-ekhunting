// dependencies
import Handlebars from 'handlebars';

// render function for prompt dialog
let PromptTemplate = data => Handlebars.compile(`
  <div class="prompt-backdrop">
    <section class="prompt-dialog {{#if icon}}has-icon{{/if}}">
      <div class="prompt-body">
        <div>
          <h2 class="prompt-title">{{title}}</h2>
          <p class="prompt-description">{{description}}</p>
        </div>
        {{#if icon}}
          <div class="prompt-icon">
            <i class="{{iconFamily}} {{iconPrefix}}{{icon}}"></i>
          </div>
        {{/if}}
      </div>
      <footer class="prompt-footer">
        <button data-dismiss>{{dismissText}}</button>
        <button class="primary" data-confirm>{{confirmText}}</button>
      </footer>
    </section>
  </div>
`)(data);

// initializer function
export default class Prompt {

  constructor(props={}) {
    this.options = {
      title: 'Prompt',
      description: 'You want to proceed?',
      icon: 'question',
      iconPrefix: 'fa-',
      iconFamily: 'far',
      dismissText: 'Dismiss',
      confirmText: 'Confirm',
      ...props
    }
    this.active = false;
  }

  render(props={}) {
    let parser = new DOMParser();
    let { options } = this;
    return parser.parseFromString(PromptTemplate({
      ...options,
      ...props
    }), 'text/html').body.firstChild;
  }

  bindElement(el) {

  }

  ask(props={},el=null) {

    if(!el)
      el = document.body;

    return new Promise((resolve, reject) => {

      this.active = true;

      let p = this.render(props)
      el.appendChild(p);
      let d = p.querySelector('[data-dismiss]');
      let c = p.querySelector('[data-confirm]');

      let remove = (choice=false) => {
        this.active = false;
        p.parentNode.removeChild(p);
        if(choice === true) return resolve({message:'I Resolved'});
        if(choice === false) return reject({message:'I dismissed'});
        return reject({message:'Unable to determine choice. Rejecting as safety grip.'});
      };

      d.addEventListener('click', e => remove(false));
      c.addEventListener('click', e => remove(true));

    });
  }

}
