/* Personal model sessions are separate from the studio login. */
import { api, esc } from './shared.js';

export function initModelConnections() {
  const $ = id => document.getElementById(id);
  const provider = $('guideprovider');
  const model = $('guidemodel');
  let connections = {};
  let locked = false;
  let signingIn = null;
  let poll = null;

  function modelOptions() {
    const options = connections[provider.value]?.models || [];
    const previous = model.value;
    model.hidden = !options.length;
    model.innerHTML = options.map(m => `<option value="${esc(m.id)}"${m.default ? ' selected' : ''}>${esc(m.label)}</option>`).join('');
    if (options.some(m => m.id === previous)) model.value = previous;
    $('guidebilling').textContent = provider.value === 'gemini'
      ? 'Powered by Gemini Pro · ready with your studio sign-in'
      : connections[provider.value]?.billing || 'Connect your personal account below.';
  }
  function render() {
    for (const name of ['chatgpt', 'claude']) {
      const c = connections[name] || {};
      $(`${name}status`).textContent = c.connected
        ? `Connected${c.plan ? ' · ' + c.plan : ''}. ${c.billing || ''}`
        : c.message || 'Not connected';
      $(`${name}signin`).disabled = locked || !!signingIn || c.available === false || c.can_sign_in === false;
      $(`${name}disconnect`).hidden = !c.connected && !c.login;
      $(`${name}disconnect`).disabled = locked;
    }
    modelOptions();
  }
  async function refresh() {
    try {
      connections = await api('/api/model-connections');
      render();
      $('modelconnectnote').textContent = '';
    } catch (e) {
      $('modelconnectnote').textContent = e.message;
    }
  }
  async function checkLogin(name, deadline) {
    try {
      const status = await api(`/api/model-connections/${name}`);
      if (signingIn !== name) return;
      connections[name] = status;
      if (status.connected) {
        signingIn = null;
        provider.value = name;
        $('modelchallenge').hidden = true;
        $('modelconnectnote').textContent = 'Connected. Your next reply will use this account.';
        render();
        return;
      }
      render();
      if (Date.now() < deadline && signingIn === name) {
        poll = setTimeout(() => checkLogin(name, deadline), 2500);
      } else {
        signingIn = null;
        $('modelconnectnote').textContent = 'Sign-in has not completed. Refresh status or start again.';
      }
    } catch (e) {
      signingIn = null;
      $('modelconnectnote').textContent = `${e.message} Use Refresh status to check the connection.`;
    }
  }
  async function signIn(name) {
    if (locked || signingIn) return;
    signingIn = name;
    $(`${name}signin`).disabled = true;
    $('modelconnectnote').textContent = 'Starting the provider’s sign-in…';
    try {
      const result = await api(`/api/model-connections/${name}/signin`, {
        method: 'POST', headers: { 'X-ZPF-Model-Connection': '1' }, body: {} });
      $('modelchallenge').hidden = !result.url;
      if (result.url) {
        const url = new URL(result.url);
        if (url.protocol !== 'https:' || url.hostname !== 'auth.openai.com') {
          throw new Error('The provider returned an unexpected sign-in address.');
        }
        $('modelauthlink').href = url.href;
        $('modelauthcode').textContent = result.code || '';
      }
      $('modelconnectnote').textContent = result.message ||
        'Open the sign-in page and enter this code. Finish sign-in there; this page will update.';
      checkLogin(name, Date.now() + 300000);
    } catch (e) {
      signingIn = null;
      $('modelconnectnote').textContent = e.message;
      render();
    }
  }
  for (const name of ['chatgpt', 'claude']) {
    $(`${name}signin`).onclick = () => signIn(name);
    $(`${name}disconnect`).onclick = async () => {
      if (locked) return;
      try {
        await api(`/api/model-connections/${name}/disconnect`, {
          method: 'POST', headers: { 'X-ZPF-Model-Connection': '1' }, body: {} });
        clearTimeout(poll);
        signingIn = null;
        $('modelchallenge').hidden = true;
        await refresh();
        $('modelconnectnote').textContent = 'Disconnected. Reconnect or choose a different creative partner.';
      } catch (e) { $('modelconnectnote').textContent = e.message; }
    };
  }
  $('modelconnecttoggle').onclick = () => {
    $('modelconnections').hidden = !$('modelconnections').hidden;
    $('modelconnecttoggle').setAttribute('aria-expanded', String(!$('modelconnections').hidden));
    if (!$('modelconnections').hidden) refresh();
  };
  $('modelrefresh').onclick = refresh;
  provider.onchange = () => {
    modelOptions();
    if (provider.value !== 'gemini') {
      $('modelconnections').hidden = false;
      $('modelconnecttoggle').setAttribute('aria-expanded', 'true');
      refresh();
    }
  };
  provider.value = "gemini";
  modelOptions();
  return {
    useStudio() {
      clearTimeout(poll); signingIn = null;
      provider.value = "gemini";
      $("modelconnections").hidden = true;
      $("modelconnecttoggle").setAttribute("aria-expanded", "false");
      modelOptions();
    },
    appendTo(form) {
      form.append('guide_provider', provider.value);
      if (model.value) form.append('guide_model', model.value);
    },
    setLocked(value) {
      locked = value;
      provider.disabled = value;
      model.disabled = value;
      for (const name of ['chatgpt', 'claude']) {
        $(`${name}signin`).disabled = value || !!signingIn || connections[name]?.available === false
          || connections[name]?.can_sign_in === false;
        $(`${name}disconnect`).disabled = value;
      }
    },
  };
}
