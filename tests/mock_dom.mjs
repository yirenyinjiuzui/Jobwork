// Shared simulated DOM; never a real-browser assertion.
export function mockedDOM() {
  class FakeInput extends EventTarget {
    constructor(label, options = {}) {
      super();
      this.tagName = options.tagName || 'INPUT';
      this.value = options.value || '';
      this.type = options.type || 'text';
      this.labels = [{ innerText: label }];
      this.id = options.id || 'input-' + label;
      this.name = options.name || '';
      this.readOnly = !!options.readOnly;
      this.disabled = !!options.disabled;
      this.connected = options.connected ?? true;
      this.visible = options.visible ?? true;
      this.form = options.form;
      this.attrs = options.attrs || {};
      this.offsetWidth = this.offsetHeight = 200;
      this.maxLength = options.maxLength || -1;
    }
    get value() { return this._value; }
    set value(x) { this._value = x; }
    getClientRects() { return this.visible ? [{}] : []; }
    closest() { return null; }
    getAttribute(k) { return this.attrs[k] || ''; }
    matches(s) { return s === ':disabled' && this.disabled; }
    get isConnected() { return this.connected; }
  }
  globalThis.__jobWorkbenchFormPreviewV113?.observer?.disconnect();
  clearTimeout(globalThis.__jobWorkbenchFormPreviewV113?.timer);
  delete globalThis.__jobWorkbenchFormPreviewV113;
  let records=[];
  globalThis.MutationObserver=class { observe(){} disconnect(){records=[];} takeRecords(){const r=records;records=[];return r;} };
  const mutate=()=>records.push({type:'childList'});
  const url = new URL('http://localhost:8765/demo-form.html');
  globalThis.location = url;
  globalThis.getComputedStyle = () => ({ visibility: 'visible', display: 'block', opacity: '1' });
  globalThis.HTMLInputElement = FakeInput;
  globalThis.HTMLTextAreaElement = FakeInput;
  const nodes = [];
  const documentEvents=new EventTarget();
  globalThis.document = {
    body: {}, documentElement: {}, visibilityState: 'visible',
    addEventListener: (...args)=>documentEvents.addEventListener(...args),
    removeEventListener: (...args)=>documentEvents.removeEventListener(...args),
    dispatchEvent: event=>documentEvents.dispatchEvent(event),
    getElementById: () => null,
    querySelectorAll: selector => selector.startsWith('input[type=') ? nodes.filter(n => n.type === 'password') : nodes,
  };
  return { nodes, FakeInput, url, mutate };
}
