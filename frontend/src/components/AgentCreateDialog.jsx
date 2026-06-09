import { useEffect, useMemo, useState } from 'react';
import { Bot, Check, PackageCheck, Search, Sparkles, X } from 'lucide-react';
import { DEFAULT_PACKAGES, packageKinds, pluginDisplayTags } from '../lib/plugins.js';

const REQUIRED_PACKAGE_IDS = ['agent.loop.react'];

export function AgentCreateDialog({
  open,
  packages,
  onCreate,
  onCancel,
}) {
  const defaultPackageIds = useMemo(() => (
    DEFAULT_PACKAGES.filter((packageId) => packages.some((item) => item.package_id === packageId))
  ), [packages]);
  const requiredPackageIds = useMemo(() => (
    REQUIRED_PACKAGE_IDS.filter((packageId) => packages.some((item) => item.package_id === packageId))
  ), [packages]);
  const modelPackageIds = useMemo(() => (
    packages.filter((pluginPackage) => packageKinds(pluginPackage).includes('model')).map((pluginPackage) => pluginPackage.package_id)
  ), [packages]);
  const defaultModelPackageId = useMemo(() => (
    defaultPackageIds.find((packageId) => modelPackageIds.includes(packageId)) || modelPackageIds[0] || ''
  ), [defaultPackageIds, modelPackageIds]);
  const defaultSelection = useMemo(() => normalizeSelection(
    [...defaultPackageIds, ...requiredPackageIds, defaultModelPackageId].filter(Boolean),
    requiredPackageIds,
    modelPackageIds,
    defaultModelPackageId,
  ), [defaultModelPackageId, defaultPackageIds, modelPackageIds, requiredPackageIds]);
  const [name, setName] = useState('研究助手');
  const [description, setDescription] = useState('由插件实例组装的轻量 Agent。');
  const [selectedPackageIds, setSelectedPackageIds] = useState(defaultSelection);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName('研究助手');
    setDescription('由插件实例组装的轻量 Agent。');
    setSelectedPackageIds(defaultSelection);
    setQuery('');
    setError('');
    setCreating(false);
  }, [defaultSelection, open]);

  const filteredPackages = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return packages;
    return packages.filter((pluginPackage) => [
      pluginPackage.name,
      pluginPackage.package_id,
      pluginPackage.description,
      ...(pluginPackage.tags || []),
    ].join(' ').toLowerCase().includes(keyword));
  }, [packages, query]);

  const groupedPackages = useMemo(() => {
    const matchingPackageIds = new Set(filteredPackages.map((pluginPackage) => pluginPackage.package_id));
    const core = packages.filter((pluginPackage) => requiredPackageIds.includes(pluginPackage.package_id) && matchingPackageIds.has(pluginPackage.package_id));
    const models = packages.filter((pluginPackage) => modelPackageIds.includes(pluginPackage.package_id) && matchingPackageIds.has(pluginPackage.package_id));
    const optional = filteredPackages.filter((pluginPackage) => (
      !requiredPackageIds.includes(pluginPackage.package_id) && !modelPackageIds.includes(pluginPackage.package_id)
    ));
    return { core, models, optional };
  }, [filteredPackages, modelPackageIds, packages, requiredPackageIds]);

  const selectedModelId = selectedPackageIds.find((packageId) => modelPackageIds.includes(packageId)) || '';

  function togglePackage(packageId) {
    if (requiredPackageIds.includes(packageId)) return;
    if (modelPackageIds.includes(packageId)) {
      setSelectedPackageIds((current) => normalizeSelection(
        [...current.filter((item) => !modelPackageIds.includes(item)), packageId],
        requiredPackageIds,
        modelPackageIds,
        packageId,
      ));
      return;
    }
    setSelectedPackageIds((current) => (
      current.includes(packageId)
        ? current.filter((item) => item !== packageId)
        : [...current, packageId]
    ));
  }

  function selectDefaultPackages() {
    setSelectedPackageIds(defaultSelection);
  }

  function selectAllOptionalPackages() {
    setSelectedPackageIds(normalizeSelection(
      packages
        .filter((pluginPackage) => !modelPackageIds.includes(pluginPackage.package_id))
        .map((pluginPackage) => pluginPackage.package_id)
        .concat(selectedModelId || defaultModelPackageId),
      requiredPackageIds,
      modelPackageIds,
      selectedModelId || defaultModelPackageId,
    ));
  }

  async function submit(event) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError('请输入智能体名称。');
      return;
    }
    if (!selectedPackageIds.length) {
      setError('至少选择一个插件。');
      return;
    }
    if (modelPackageIds.length && !selectedModelId) {
      setError('请选择一个模型插件。');
      return;
    }
    setCreating(true);
    setError('');
    try {
      await onCreate({
        name: trimmedName,
        description: description.trim(),
        packageIds: selectedPackageIds,
      });
      onCancel();
    } catch (event) {
      setError(event.message || '创建失败');
    } finally {
      setCreating(false);
    }
  }

  if (!open) return null;

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onCancel}>
      <section className="agent-create-dialog" role="dialog" aria-modal="true" aria-labelledby="agent-create-title" onMouseDown={(event) => event.stopPropagation()}>
        <button className="dialog-close-button" onClick={onCancel} aria-label="关闭弹窗">
          <X size={16} />
        </button>
        <header className="agent-create-head">
          <div className="dialog-icon success"><Bot size={20} /></div>
          <div>
            <h2 id="agent-create-title">新建智能体</h2>
            <p>填写基础信息，并选择要装配到这个智能体里的插件。</p>
          </div>
        </header>

        <form className="agent-create-form" onSubmit={submit}>
          <div className="agent-create-fields">
            <label className="agent-field">
              <span>名称</span>
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：研究助手" maxLength={64} autoFocus />
            </label>
            <label className="agent-field">
              <span>描述</span>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="描述这个智能体的用途" rows={3} maxLength={180} />
            </label>
          </div>

          <section className="agent-plugin-picker">
            <div className="agent-plugin-toolbar">
              <div>
                <strong>装配插件</strong>
                <span>{selectedPackageIds.length} / {packages.length} 个已选择</span>
              </div>
              <div className="agent-plugin-actions">
                <button type="button" className="ghost-light-button" onClick={selectDefaultPackages}>
                  <Sparkles size={14} />默认组合
                </button>
                <button type="button" className="ghost-light-button" onClick={selectAllOptionalPackages}>
                  <Check size={14} />全选可选
                </button>
              </div>
            </div>
            <label className="agent-plugin-search">
              <Search size={15} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索插件" />
            </label>
            <div className="agent-plugin-list">
              {groupedPackages.core.length > 0 && (
                <PluginGroup title="核心运行" description="智能体运行循环，创建时必须装配。">
                  {groupedPackages.core.map((pluginPackage) => renderPluginOption(pluginPackage, { required: true }))}
                </PluginGroup>
              )}
              {groupedPackages.models.length > 0 && (
                <PluginGroup title="模型插件" description="选择一个模型 provider，避免多个模型能力冲突。">
                  {groupedPackages.models.map((pluginPackage) => renderPluginOption(pluginPackage, { model: true }))}
                </PluginGroup>
              )}
              {groupedPackages.optional.length > 0 && (
                <PluginGroup title="可选插件" description="记忆、工具、技能和其它扩展能力。">
                  {groupedPackages.optional.map((pluginPackage) => renderPluginOption(pluginPackage))}
                </PluginGroup>
              )}
              {!filteredPackages.length && <p className="empty">没有匹配的插件。</p>}
            </div>
          </section>

          {error && <div className="field-error">{error}</div>}
          <div className="dialog-actions agent-create-actions">
            <button type="button" className="dialog-cancel-button" onClick={onCancel}>取消</button>
            <button type="submit" className="dialog-confirm-button success" disabled={creating || !name.trim() || !selectedPackageIds.length || (modelPackageIds.length > 0 && !selectedModelId)}>
              {creating ? '创建中' : '创建智能体'}
            </button>
          </div>
        </form>
      </section>
    </div>
  );

  function renderPluginOption(pluginPackage, options = {}) {
    const selected = selectedPackageIds.includes(pluginPackage.package_id);
    const inputType = options.model ? 'radio' : 'checkbox';
    const badge = options.required ? '必选' : options.model ? '模型' : '';
    return (
      <label className={selected ? 'agent-plugin-option selected' : 'agent-plugin-option'} key={pluginPackage.package_id}>
        <input
          type={inputType}
          name={options.model ? 'model-plugin' : undefined}
          checked={selected}
          disabled={options.required}
          onChange={() => togglePackage(pluginPackage.package_id)}
        />
        <span className="plugin-check"><PackageCheck size={16} /></span>
        <span className="plugin-option-main">
          <span className="plugin-option-title">
            <strong>{pluginPackage.name}</strong>
            {badge && <b>{badge}</b>}
          </span>
          <code>{pluginPackage.package_id}</code>
          <small>{pluginPackage.description}</small>
          <span className="tag-list compact-tags">
            {pluginDisplayTags(pluginPackage).slice(0, 4).map((tag) => <em key={`${pluginPackage.package_id}-${tag}`}>{tag}</em>)}
          </span>
        </span>
      </label>
    );
  }
}

function PluginGroup({ title, description, children }) {
  return (
    <section className="agent-plugin-group">
      <div className="agent-plugin-group-head">
        <strong>{title}</strong>
        <span>{description}</span>
      </div>
      <div className="agent-plugin-options-grid">{children}</div>
    </section>
  );
}

function normalizeSelection(packageIds, requiredPackageIds, modelPackageIds, preferredModelId) {
  const modelId = packageIds.find((packageId) => modelPackageIds.includes(packageId)) || preferredModelId;
  const withoutModels = packageIds.filter((packageId) => !modelPackageIds.includes(packageId));
  return uniqueItems([...withoutModels, ...requiredPackageIds, modelId].filter(Boolean));
}

function uniqueItems(items) {
  const seen = new Set();
  return items.filter((item) => {
    if (!item || seen.has(item)) return false;
    seen.add(item);
    return true;
  });
}
