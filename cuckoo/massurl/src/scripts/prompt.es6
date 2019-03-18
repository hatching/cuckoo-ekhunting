// dependencies
import Handlebars from 'handlebars';

// render function for prompt dialog
let PromptTemplate = data => Handlebars.compile(`
  <div class="prompt-backdrop">
    <section class="prompt-dialog">
      <div class="prompt-body">
        <h2><i class="fas fa-{{icon}}"></i> {{title}}</h2>
        <p>{{description}}</p>
      </div>
      <footer class="prompt-footer">
        <button class="button secondary" data-dismiss>{{dismissText}}</button>
        <button class="button" data-confirm>{{confirmText}}</button>
      </footer>
    </section>
  </div>
`)(data);

// initializer function
export default class Prompt {

  render(props={}) {
    let parser = new DOMParser();
    return parser.parseFromString(PromptTemplate({
      title: 'Prompt',
      description: 'You want to proceed?',
      icon: 'question',
      dismissText: 'Dismiss',
      confirmText: 'Confirm',
      ...props
    }), 'text/html').body.firstChild;
  }

  ask(props={},el=null) {

    if(!el)
      el = document.body;

    return new Promise((resolve, reject) => {

      let p = this.render(props)
      el.appendChild(p);
      let d = p.querySelector('[data-dismiss]');
      let c = p.querySelector('[data-confirm]');

      let remove = () => p.parentNode.removeChild(p);

      d.addEventListener('click', e => {
        remove();
        reject();
      });

      c.addEventListener('click', e => {
        remove();
        resolve();
      });

    });
  }

}
