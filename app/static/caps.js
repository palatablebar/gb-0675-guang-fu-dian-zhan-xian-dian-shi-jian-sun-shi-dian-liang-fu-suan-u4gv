// 上限依据：上传校验、列表、切换重算（事务，失败自动回滚）、审计与原始凭据下载。
const capPage = document.querySelector('#cap-import');
if (capPage) {
  const runId = document.body.dataset.runId;
  const feedback = document.querySelector('#cap-feedback');
  const listEl = document.querySelector('#cap-list');
  const capFile = document.querySelector('#cap-file');
  const capText = document.querySelector('#cap-text');

  capFile.addEventListener('change', async () => {
    const file = capFile.files[0];
    if (!file) return;
    if (file.size > 2000000) { capText.value = ''; alert('文件超过2MB，请缩小后导入'); return; }
    const bytes = await file.arrayBuffer();
    try { capText.value = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
    catch (e) { capText.value = new TextDecoder('gb18030', { fatal: true }).decode(bytes); }
  });

  async function refresh() {
    const [basesRes, auditRes] = await Promise.all([
      fetch('/api/cap-bases'),
      fetch(`/api/runs/${runId}/cap-audit`)
    ]);
    const bases = (await basesRes.json()).bases;
    const audit = await auditRes.json();
    const applied = audit.applied_basis;
    document.querySelector('#cap-applied').textContent = '当前 ' + (applied || '—');
    listEl.innerHTML = bases.map(b => `
      <div class="cap-item ${b.basis_id === applied ? 'is-applied' : ''}">
        <div><b>${b.basis_id}</b> <span>${b.label}</span>
          <small>有效窗口 ${b.windows.length} · 隔离 ${b.quarantine.length} · ${b.created_at}</small></div>
        <div class="cap-item-actions">
          <a class="export" href="/api/cap-bases/${b.basis_id}/raw">原始凭据</a>
          <button data-basis="${b.basis_id}" ${b.basis_id === applied ? 'disabled' : ''}>
            ${b.basis_id === applied ? '已采用' : '切换并仅重算受牵连时段'}
          </button>
        </div>
      </div>`).join('') + (audit.audit.length ? `
      <h3>切换审计</h3>
      <div class="table-scroll"><table><thead><tr><th>时间</th><th>动作</th><th>原依据</th><th>新依据</th><th>受牵连切片</th></tr></thead>
      <tbody>${audit.audit.map(a => `<tr><td>${a.created_at}</td><td>${a.action}</td><td>${a.from_basis || '—'}</td><td>${a.to_basis}</td><td>${a.affected_segments}</td></tr>`).join('')}</tbody></table></div>` : '');
    listEl.querySelectorAll('button[data-basis]').forEach(btn => btn.addEventListener('click', () => switchBasis(btn.dataset.basis)));
  }

  async function switchBasis(basisId) {
    feedback.textContent = '切换中（事务内重算，中断将恢复旧版）…';
    try {
      const res = await fetch(`/api/runs/${runId}/cap-basis`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ basis_id: basisId })
      });
      const data = await res.json();
      if (!res.ok) throw Error(data.detail);
      feedback.textContent = data.changed
        ? `已切换，受牵连切片 ${data.affected_segments} 段，其余时段保持不变。`
        : '同一依据重试：结果无新增，原始凭据未改动。';
      const url = new URL(location.href);
      url.searchParams.set('run_id', runId);
      setTimeout(() => location.href = url.toString(), 500);
    } catch (err) {
      feedback.textContent = '切换失败已回滚：' + err.message;
    }
  }

  capPage.addEventListener('click', async () => {
    capPage.disabled = true;
    feedback.textContent = '上传校验中…';
    try {
      const res = await fetch('/api/cap-bases', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_text: capText.value, label: document.querySelector('#cap-label').value })
      });
      const data = await res.json();
      if (!res.ok) throw Error(data.detail);
      feedback.textContent = `依据 ${data.basis_id} 已保存原始凭据，有效窗口 ${data.windows.length}，隔离 ${data.quarantine.length}。`;
      await refresh();
    } catch (err) {
      feedback.textContent = err.message;
    } finally {
      capPage.disabled = false;
    }
  });

  refresh();
}
