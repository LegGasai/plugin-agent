import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Bot, Check, PackageCheck, Plus, Search, Sparkles, X } from 'lucide-react';
import { DEFAULT_PACKAGES, packageKinds, pluginDisplayTags, selectDefaultPackageVersions } from '../lib/plugins.js';

const REQUIRED_PACKAGE_IDS = ['agent.loop.react'];

export function AgentCreateDialog({
  open,
  mode = 'create',
  agent = null,
  packages,
  onCreate,
  onCancel,
}) {
  const isEdit = mode === 'edit';
  const availablePackages = useMemo(() => selectDefaultPackageVersions(packages), [packages]);
  const defaultPackageIds = useMemo(() => (
    DEFAULT_PACKAGES.filter((packageId) => availablePackages.some((item) => item.package_id === packageId))
  ), [availablePackages]);
  const requiredPackageIds = useMemo(() => (
    REQUIRED_PACKAGE_IDS.filter((packageId) => availablePackages.some((item) => item.package_id === packageId))
  ), [availablePackages]);
  const modelPackageIds = useMemo(() => (
    availablePackages.filter((pluginPackage) => packageKinds(pluginPackage).includes('model')).map((pluginPackage) => pluginPackage.package_id)
  ), [availablePackages]);
  const defaultModelPackageId = useMemo(() => (
    defaultPackageIds.find((packageId) => modelPackageIds.includes(packageId)) || modelPackageIds[0] || ''
  ), [defaultPackageIds, modelPackageIds]);
  const defaultSelection = useMemo(() => normalizeSelection(
    [...defaultPackageIds, ...requiredPackageIds, defaultModelPackageId].filter(Boolean),
    requiredPackageIds,
    modelPackageIds,
    defaultModelPackageId,
  ), [defaultModelPackageId, defaultPackageIds, modelPackageIds, requiredPackageIds]);
  const agentPackageIds = useMemo(() => {
    if (!agent) return [];
    const instancePackageIds = (agent.plugin_instances || []).map((instance) => instance.package_id);
    return instancePackageIds.length ? instancePackageIds : (agent.plugin_ids || []);
  }, [agent]);
  const editSelection = useMemo(() => {
    const selectedModelPackageId = agentPackageIds.find((packageId) => modelPackageIds.includes(packageId)) || defaultModelPackageId;
    return normalizeSelection(agentPackageIds, requiredPackageIds, modelPackageIds, selectedModelPackageId);
  }, [agentPackageIds, defaultModelPackageId, modelPackageIds, requiredPackageIds]);
  const initialSelection = isEdit ? editSelection : defaultSelection;
  const [name, setName] = useState('研究助手');
  const [description, setDescription] = useState('由插件实例组装的轻量 Agent。');
  const [selectedPackageIds, setSelectedPackageIds] = useState(initialSelection);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(isEdit ? (agent?.name || '') : '研究助手');
    setDescription(isEdit ? (agent?.description || '') : '由插件实例组装的轻量 Agent。');
    setSelectedPackageIds(initialSelection);
    setQuery('');
    setError('');
    setCreating(false);
  }, [agent, initialSelection, isEdit, open]);

  const filteredPackages = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return availablePackages;
    return availablePackages.filter((pluginPackage) => [
      pluginPackage.name,
      pluginPackage.package_id,
      pluginPackage.description,
      ...(pluginPackage.tags || []),
    ].join(' ').toLowerCase().includes(keyword));
  }, [availablePackages, query]);

  const groupedPackages = useMemo(() => {
    const matchingPackageIds = new Set(filteredPackages.map((pluginPackage) => pluginPackage.package_id));
    const core = availablePackages.filter((pluginPackage) => requiredPackageIds.includes(pluginPackage.package_id) && matchingPackageIds.has(pluginPackage.package_id));
    const models = availablePackages.filter((pluginPackage) => modelPackageIds.includes(pluginPackage.package_id) && matchingPackageIds.has(pluginPackage.package_id));
    const optional = filteredPackages.filter((pluginPackage) => (
      !requiredPackageIds.includes(pluginPackage.package_id) && !modelPackageIds.includes(pluginPackage.package_id)
    ));
    return { core, models, optional };
  }, [availablePackages, filteredPackages, modelPackageIds, requiredPackageIds]);

  const selectedModelId = selectedPackageIds.find((packageId) => modelPackageIds.includes(packageId)) || '';
  const dependencyReport = useMemo(
    () => analyzePackageDependencies(availablePackages, selectedPackageIds),
    [availablePackages, selectedPackageIds],
  );
  const hasBlockingDependencies = dependencyReport.requiredMissing.length > 0;

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

  function addProviderPackage(packageId) {
    setSelectedPackageIds((current) => normalizeSelection(
      [...current, packageId],
      requiredPackageIds,
      modelPackageIds,
      modelPackageIds.includes(packageId) ? packageId : selectedModelId || defaultModelPackageId,
    ));
  }

  function selectDefaultPackages() {
    setSelectedPackageIds(defaultSelection);
  }

  function selectAllOptionalPackages() {
    setSelectedPackageIds(normalizeSelection(
      availablePackages
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
    if (hasBlockingDependencies) {
      setError(`请先补齐插件依赖后再${isEdit ? '保存' : '创建'}智能体。`);
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
      setError(event.message || (isEdit ? '保存失败' : '创建失败'));
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
            <h2 id="agent-create-title">{isEdit ? '编辑智能体' : '新建智能体'}</h2>
            <p>{isEdit ? '调整智能体基础信息和插件装配，保存后工作台会使用新的运行环境。' : '填写基础信息，并选择要装配到这个智能体里的插件。'}</p>
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
                <span>{selectedPackageIds.length} / {availablePackages.length} 个已选择</span>
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
            <DependencyGuide report={dependencyReport} onAddPackage={addProviderPackage} />
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
            <button type="submit" className="dialog-confirm-button success" disabled={creating || !name.trim() || !selectedPackageIds.length || (modelPackageIds.length > 0 && !selectedModelId) || hasBlockingDependencies}>
              {creating ? (isEdit ? '保存中' : '创建中') : (isEdit ? '保存智能体' : '创建智能体')}
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

function DependencyGuide({ report, onAddPackage }) {
  if (!report.requiredMissing.length && !report.optionalMissing.length) return null;
  const allItems = [...report.requiredMissing, ...report.optionalMissing];
  const items = allItems.slice(0, 3);
  const overflowCount = Math.max(0, allItems.length - items.length);
  return (
    <section className={report.requiredMissing.length ? 'agent-dependency-guide blocking' : 'agent-dependency-guide'}>
      <div className="agent-dependency-head">
        <AlertTriangle size={15} />
        <strong>{report.requiredMissing.length ? '需要补齐插件依赖' : '可选依赖未装配'}</strong>
        <span>{report.requiredMissing.length ? '缺少必需能力时无法创建。' : '缺少可选能力时运行可能降级。'}</span>
        {overflowCount > 0 && <em>还有 {overflowCount} 项</em>}
      </div>
      <div className="agent-dependency-list">
        {items.map((item) => (
          <div className="agent-dependency-item" key={`${item.pluginPackage.package_id}-${item.dependency.capability}-${item.reason}`}>
            <span>
              <strong>{item.pluginPackage.name}</strong>
              <small>{dependencyMessage(item)}</small>
            </span>
            <div className="agent-dependency-actions">
              {item.candidates.slice(0, 3).map((candidate) => (
                <button type="button" className="mini-button" key={candidate.package_id} onClick={() => onAddPackage(candidate.package_id)}>
                  <Plus size={13} />{candidate.name}
                </button>
              ))}
              {!item.candidates.length && <em>当前未安装可提供该能力的插件</em>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function dependencyMessage(item) {
  const version = item.dependency.version || '*';
  if (item.reason === 'version_mismatch') {
    return `需要 ${item.dependency.capability} ${version}，已选 provider 版本不满足。`;
  }
  return `需要 ${item.dependency.capability} ${version}，请添加一个 provider。`;
}

function analyzePackageDependencies(packages, selectedPackageIds) {
  const selectedIds = new Set(selectedPackageIds);
  const selectedPackages = packages.filter((pluginPackage) => selectedIds.has(pluginPackage.package_id));
  const selectedProviders = collectProviders(selectedPackages);
  const allProviders = collectProviders(packages);
  const missing = [];

  for (const pluginPackage of selectedPackages) {
    for (const dependency of pluginPackage.requires || []) {
      const providers = selectedProviders.get(dependency.capability) || [];
      const satisfyingProviders = providers.filter((provider) => satisfiesCapabilityVersion(provider.capability.version, dependency.version));
      if (satisfyingProviders.length) continue;
      const candidates = (allProviders.get(dependency.capability) || [])
        .filter((provider) => !selectedIds.has(provider.pluginPackage.package_id))
        .filter((provider) => satisfiesCapabilityVersion(provider.capability.version, dependency.version))
        .map((provider) => provider.pluginPackage);
      missing.push({
        pluginPackage,
        dependency,
        required: dependency.required !== false,
        reason: providers.length ? 'version_mismatch' : 'missing',
        candidates: uniquePackages(candidates),
      });
    }
  }

  return {
    requiredMissing: missing.filter((item) => item.required),
    optionalMissing: missing.filter((item) => !item.required),
  };
}

function collectProviders(packages) {
  const providers = new Map();
  for (const pluginPackage of packages) {
    for (const capability of pluginPackage.provides || []) {
      const list = providers.get(capability.name) || [];
      list.push({ pluginPackage, capability });
      providers.set(capability.name, list);
    }
  }
  return providers;
}

function satisfiesCapabilityVersion(providedVersion = '1.0.0', range = '>=0.0.0') {
  if (!range || range === '*') return true;
  const comparators = String(range).split(/[,\s]+/).filter(Boolean);
  return comparators.every((comparator) => satisfiesComparator(providedVersion, comparator));
}

function satisfiesComparator(providedVersion, comparator) {
  const match = String(comparator).match(/^(>=|<=|>|<|==|=)?(.+)$/);
  if (!match) return true;
  const operator = match[1] || '=';
  const target = match[2];
  const comparison = compareVersions(providedVersion, target);
  if (operator === '>=') return comparison >= 0;
  if (operator === '<=') return comparison <= 0;
  if (operator === '>') return comparison > 0;
  if (operator === '<') return comparison < 0;
  return comparison === 0;
}

function compareVersions(left, right) {
  const leftParts = String(left).split('.').map((part) => Number.parseInt(part, 10) || 0);
  const rightParts = String(right).split('.').map((part) => Number.parseInt(part, 10) || 0);
  const length = Math.max(leftParts.length, rightParts.length, 3);
  for (let index = 0; index < length; index += 1) {
    const diff = (leftParts[index] || 0) - (rightParts[index] || 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

function normalizeSelection(packageIds, requiredPackageIds, modelPackageIds, preferredModelId) {
  const modelId = packageIds.find((packageId) => modelPackageIds.includes(packageId)) || preferredModelId;
  const withoutModels = packageIds.filter((packageId) => !modelPackageIds.includes(packageId));
  return uniqueItems([...withoutModels, ...requiredPackageIds, modelId].filter(Boolean));
}

function uniquePackages(packages) {
  const seen = new Set();
  return packages.filter((pluginPackage) => {
    if (seen.has(pluginPackage.package_id)) return false;
    seen.add(pluginPackage.package_id);
    return true;
  });
}

function uniqueItems(items) {
  const seen = new Set();
  return items.filter((item) => {
    if (!item || seen.has(item)) return false;
    seen.add(item);
    return true;
  });
}
