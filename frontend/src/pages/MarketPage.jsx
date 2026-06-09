import { useEffect, useMemo, useRef, useState } from 'react';
import { Cable, Download, FileArchive, FolderOpen, PackageOpen, RefreshCw, Search, Trash2, Upload, X } from 'lucide-react';
import { installMarketPlugin, loadMarketplace, uninstallInstalledPlugin, uploadMarketPlugin } from '../lib/api.js';
import { normalizePackage, packageKinds, pluginDisplayTags, resourceLabel, runtimeLabel } from '../lib/plugins.js';

const TYPE_FILTERS = [
  { id: 'all', label: '全部' },
  { id: 'model', label: '模型' },
  { id: 'tool', label: '工具' },
  { id: 'memory', label: '记忆' },
  { id: 'skill', label: '技能' },
  { id: 'agent_loop', label: 'Agent Loop' },
  { id: 'mcp_server', label: 'MCP' },
  { id: 'extension', label: '扩展' },
];

export function MarketPage({ packages, apiBase, onMarketplaceChanged }) {
  const [activeTab, setActiveTab] = useState('installed');
  const [query, setQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [tagFilter, setTagFilter] = useState('');
  const [installedPackages, setInstalledPackages] = useState(packages);
  const [marketInfo, setMarketInfo] = useState({ market_plugin_packages: [] });
  const packageInputRef = useRef(null);
  const directoryInputRef = useRef(null);
  const [uploadMenuOpen, setUploadMenuOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [actionStatus, setActionStatus] = useState('');
  const [actionError, setActionError] = useState('');
  const [selectedPackage, setSelectedPackage] = useState(null);

  useEffect(() => {
    setInstalledPackages(packages);
  }, [packages]);

  useEffect(() => {
    refreshMarketplaceInfo();
  }, []);

  useEffect(() => {
    setSelectedPackage(null);
  }, [activeTab]);

  const marketPluginPackages = useMemo(() => (
    (marketInfo.plugin_packages || marketInfo.market_plugin_packages || []).map(normalizePackage)
  ), [marketInfo.plugin_packages, marketInfo.market_plugin_packages]);

  const tagOptions = useMemo(() => (
    [...new Set([...installedPackages, ...marketPluginPackages].flatMap((pluginPackage) => pluginPackage.tags || []))]
      .sort((left, right) => left.localeCompare(right, 'zh-Hans-CN'))
  ), [installedPackages, marketPluginPackages]);

  const activePackages = activeTab === 'marketplace' ? marketPluginPackages : installedPackages;
  const filteredPackages = useMemo(() => activePackages.filter((pluginPackage) => {
    const text = [
      pluginPackage.name,
      pluginPackage.package_id,
      pluginPackage.description,
      pluginPackage.runtime?.type,
      runtimeLabel(pluginPackage.runtime?.type),
      ...(pluginPackage.tags || []),
    ].join(' ').toLowerCase();
    const matchesQuery = !query.trim() || text.includes(query.trim().toLowerCase());
    const matchesType = typeFilter === 'all' || packageKinds(pluginPackage).includes(typeFilter);
    const matchesTag = !tagFilter || (pluginPackage.tags || []).includes(tagFilter);
    return matchesQuery && matchesType && matchesTag;
  }), [activePackages, query, typeFilter, tagFilter]);

  async function refreshMarketplaceInfo() {
    try {
      const data = await loadMarketplace();
      setMarketInfo(data);
    } catch (event) {
      setActionError(`读取插件包失败：${event.message}`);
    }
  }

  async function uploadPackage(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    setUploading(true);
    setUploadMenuOpen(false);
    setActionStatus(files.length === 1 ? `正在上传 ${files[0].name}` : `正在上传 ${files.length} 个插件文件`);
    setActionError('');
    try {
      await uploadMarketPlugin(files);
      setActionStatus('插件包已上传');
      await refreshMarketplaceInfo();
    } catch (event) {
      setActionError(`上传失败：${event.message}`);
      setActionStatus('');
    } finally {
      setUploading(false);
    }
  }

  function selectPackageFile(event) {
    uploadPackage(event.target.files);
    event.target.value = '';
  }

  function selectDirectory(event) {
    uploadPackage(event.target.files);
    event.target.value = '';
  }

  async function installPackage(pluginPackage) {
    setActionStatus(`正在安装 ${pluginPackage.name}`);
    setActionError('');
    try {
      await installMarketPlugin(pluginPackage.package_id, pluginPackage.version);
      setActionStatus(`${pluginPackage.name} 已安装`);
      setSelectedPackage((current) => (
        current?.package_id === pluginPackage.package_id && current?.version === pluginPackage.version
          ? { ...current, installed: true }
          : current
      ));
      await refreshMarketplaceInfo();
      await onMarketplaceChanged?.();
    } catch (event) {
      setActionError(`安装失败：${event.message}`);
      setActionStatus('');
    }
  }

  async function uninstallPackage(pluginPackage) {
    if (!window.confirm(`确定卸载 ${pluginPackage.name} 吗？`)) return;
    setActionStatus(`正在卸载 ${pluginPackage.name}`);
    setActionError('');
    try {
      await uninstallInstalledPlugin(pluginPackage.package_id, pluginPackage.version);
      setActionStatus(`${pluginPackage.name} 已卸载`);
      setSelectedPackage(null);
      await refreshMarketplaceInfo();
      await onMarketplaceChanged?.();
    } catch (event) {
      setActionError(`卸载失败：${event.message}`);
      setActionStatus('');
    }
  }

  function openPackageDetails(pluginPackage) {
    setSelectedPackage(pluginPackage);
  }

  return (
    <section className="page-panel market-page">
      <header className="market-topbar">
        <div className="market-tabs" aria-label="插件市场视图">
          <button className={activeTab === 'installed' ? 'market-tab active' : 'market-tab'} onClick={() => setActiveTab('installed')}>
            插件
            <span>{installedPackages.length}</span>
          </button>
          <button className={activeTab === 'marketplace' ? 'market-tab active' : 'market-tab'} onClick={() => setActiveTab('marketplace')}>
            探索 Marketplace
            <span>{marketPluginPackages.length}</span>
          </button>
        </div>
        <div className="market-actions">
          <div className="runtime-pill"><Cable size={15} />{apiBase}</div>
          <div className="market-upload-action">
            <button className="primary-button" onClick={() => setUploadMenuOpen((open) => !open)} disabled={uploading}>
              <Upload size={15} />上传插件包
            </button>
            {uploadMenuOpen && (
              <div className="upload-menu">
                <button type="button" onClick={() => packageInputRef.current?.click()}>
                  <FileArchive size={15} />选择压缩包
                </button>
                <button type="button" onClick={() => directoryInputRef.current?.click()}>
                  <FolderOpen size={15} />选择插件目录
                </button>
              </div>
            )}
            <input
              ref={packageInputRef}
              className="hidden-file-input"
              type="file"
              accept=".pluginpkg,.zip"
              onChange={selectPackageFile}
            />
            <input
              ref={directoryInputRef}
              className="hidden-file-input"
              type="file"
              multiple
              webkitdirectory=""
              directory=""
              onChange={selectDirectory}
            />
          </div>
          <button className="icon-button" onClick={refreshMarketplaceInfo} aria-label="刷新插件包" title="刷新插件包"><RefreshCw size={15} /></button>
        </div>
      </header>

      <div className="market-content">
        <section className="market-hero">
          <h1>{activeTab === 'marketplace' ? '探索 Marketplace' : '插件'}</h1>
          <p>
            {activeTab === 'marketplace'
              ? '浏览插件市场中可下载到当前环境的模型、工具、记忆、技能与 Agent Loop 插件包。'
              : '查看当前环境已安装与内置的模型、工具、记忆、技能与 Agent Loop 插件包。'}
          </p>
          <div className="market-searchbar">
            <select className="market-tag-select" value={tagFilter} onChange={(event) => setTagFilter(event.target.value)} aria-label="按标签筛选插件">
              <option value="">所有标签</option>
              {tagOptions.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
            </select>
            <label className="market-search">
              <Search size={16} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索插件" />
            </label>
          </div>
          <nav className="market-category-row" aria-label="插件类型">
            {TYPE_FILTERS.map((filter) => (
              <button
                key={filter.id}
                className={typeFilter === filter.id ? 'market-category active' : 'market-category'}
                onClick={() => setTypeFilter(filter.id)}
              >
                {filter.label}
              </button>
            ))}
          </nav>
        </section>

        {(actionStatus || actionError) && (
          <div className={actionError ? 'market-action-message error' : 'market-action-message'}>
            {actionError || actionStatus}
          </div>
        )}

        <section className="market-results">
          <div className="market-section-head">
            <div>
              <strong>{activeTab === 'marketplace' ? '市场插件包' : '已安装与内置插件'}</strong>
              <span>{filteredPackages.length} / {activePackages.length} 个插件包{tagFilter ? ` · ${tagFilter}` : ''}</span>
            </div>
          </div>

          <div className="market-grid">
            {filteredPackages.map((pluginPackage) => {
              const resources = pluginPackage.resources || [];
              const primaryKind = resources[0]?.kind || 'extension';
              return (
                <article
                  className="market-card"
                  key={`${pluginPackage.package_id}-${pluginPackage.version}`}
                  onClick={() => openPackageDetails(pluginPackage)}
                >
                  <div className="market-plugin-icon"><PackageOpen size={22} /></div>
                  <div className="market-card-main">
                    <div className="market-card-title">
                      <strong>{pluginPackage.name}</strong>
                      <span>v{pluginPackage.version}</span>
                    </div>
                    <code>{pluginPackage.package_id}</code>
                    <p>{pluginPackage.description}</p>
                    <div className="market-card-meta">
                      <span>{runtimeLabel(pluginPackage.runtime?.type)}</span>
                      <span>{resources.length} 资源</span>
                      <span>{pluginPackage.provides?.length || 0} 能力</span>
                    </div>
                    <div className="tag-list">
                      {pluginDisplayTags(pluginPackage).map((tag) => <span key={`tag-${tag}`}>{tag}</span>)}
                    </div>
                    {activeTab === 'marketplace' && (
                      <div className="market-card-actions">
                        <button className="mini-button" onClick={(event) => { event.stopPropagation(); installPackage(pluginPackage); }} disabled={pluginPackage.installed}>
                          <Download size={14} />{pluginPackage.installed ? '已安装' : '安装'}
                        </button>
                      </div>
                    )}
                    {activeTab === 'installed' && pluginPackage.source === 'installed' && (
                      <div className="market-card-actions">
                        <button className="mini-button danger" onClick={(event) => { event.stopPropagation(); uninstallPackage(pluginPackage); }}>
                          <Trash2 size={14} />卸载
                        </button>
                      </div>
                    )}
                  </div>
                  <span className="market-kind-badge">{resourceLabel(primaryKind)}</span>
                </article>
              );
            })}
            {!filteredPackages.length && (
              <div className="market-empty">
                <PackageOpen size={22} />
                <strong>{activeTab === 'marketplace' ? '市场暂无匹配插件' : '没有匹配的插件'}</strong>
                <span>{activeTab === 'marketplace' ? '可以上传插件包，或调整搜索与类型筛选。' : '调整搜索关键词或切换类型筛选。'}</span>
              </div>
            )}
          </div>
        </section>
      </div>
      {selectedPackage && (
        <PluginDetailDrawer
          pluginPackage={selectedPackage}
          view={activeTab}
          onClose={() => setSelectedPackage(null)}
          onInstall={installPackage}
          onUninstall={uninstallPackage}
        />
      )}
    </section>
  );
}

function PluginDetailDrawer({ pluginPackage, view, onClose, onInstall, onUninstall }) {
  const resources = pluginPackage.resources || [];
  const provides = pluginPackage.provides || [];
  const requires = pluginPackage.requires || [];
  const schemas = pluginPackage.schemas || [];
  return (
    <aside className="plugin-detail-drawer" aria-label="插件详情">
      <header className="plugin-detail-head">
        <div>
          <strong>{pluginPackage.name}</strong>
          <span>{pluginPackage.package_id}</span>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="关闭插件详情"><X size={16} /></button>
      </header>

      <div className="plugin-detail-body">
        <p>{pluginPackage.description}</p>
        <div className="plugin-detail-kv">
          <span>版本</span><strong>v{pluginPackage.version}</strong>
          <span>来源</span><strong>{sourceLabel(pluginPackage.source)}</strong>
          <span>运行时</span><strong>{runtimeLabel(pluginPackage.runtime?.type)}</strong>
          <span>入口</span><strong>{pluginPackage.entrypoint || pluginPackage.runtime?.entrypoint || '-'}</strong>
          <span>状态</span><strong>{pluginPackage.installed ? '已安装' : view === 'marketplace' ? '可安装' : '可用'}</strong>
        </div>

        <DetailSection title="能力" emptyText="未声明能力">
          {provides.map((capability) => (
            <div className="detail-list-item" key={`${capability.name}-${capability.version || ''}`}>
              <strong>{capability.name}</strong>
              <span>v{capability.version || '1.0.0'}</span>
            </div>
          ))}
        </DetailSection>

        <DetailSection title="资源" emptyText="未声明资源">
          {resources.map((resource) => (
            <div className="detail-list-item" key={`${resource.kind}-${resource.id}`}>
              <strong>{resource.title || resource.id}</strong>
              <span>{resourceLabel(resource.kind)} · {resource.invoke_capability || resource.id}</span>
            </div>
          ))}
        </DetailSection>

        <DetailSection title="依赖" emptyText="未声明依赖">
          {requires.map((dependency) => (
            <div className="detail-list-item" key={`${dependency.capability}-${dependency.version || ''}`}>
              <strong>{dependency.capability}</strong>
              <span>{dependency.required === false ? 'optional' : 'required'} · {dependency.version || '*'}</span>
            </div>
          ))}
        </DetailSection>

        <DetailSection title="Schema" emptyText="未声明 Schema">
          {schemas.map((schema) => (
            <SchemaCard schema={schema} key={schema.schema_ref} />
          ))}
        </DetailSection>
      </div>

      <footer className="plugin-detail-actions">
        {view === 'marketplace' && (
          <button className="primary-button" onClick={() => onInstall(pluginPackage)} disabled={pluginPackage.installed}>
            <Download size={15} />{pluginPackage.installed ? '已安装' : '安装'}
          </button>
        )}
        {view === 'installed' && pluginPackage.source === 'installed' && (
          <button className="danger-button" onClick={() => onUninstall(pluginPackage)}>
            <Trash2 size={15} />卸载
          </button>
        )}
      </footer>
    </aside>
  );
}

function DetailSection({ title, emptyText, children }) {
  const items = Array.isArray(children) ? children.filter(Boolean) : children;
  const isEmpty = Array.isArray(items) ? items.length === 0 : !items;
  return (
    <section className="plugin-detail-section">
      <strong>{title}</strong>
      {isEmpty ? <span className="detail-empty">{emptyText}</span> : <div className="detail-list">{items}</div>}
    </section>
  );
}

function SchemaCard({ schema }) {
  const jsonSchema = schema.json_schema || {};
  return (
    <details className="schema-card">
      <summary className="schema-card-head">
        <strong>{schema.schema_ref}</strong>
        <span>{schemaTypeLabel(jsonSchema)}</span>
      </summary>
      {jsonSchema.description && <p>{jsonSchema.description}</p>}
      <pre className="schema-code"><code>{JSON.stringify(jsonSchema, null, 2)}</code></pre>
    </details>
  );
}

function schemaTypeLabel(schema) {
  if (!schema) return 'any';
  if (schema.type === 'array') return `${schemaTypeName(schema.type)}<${schemaTypeLabel(schema.items || {})}>`;
  if (Array.isArray(schema.type)) return schema.type.map(schemaTypeName).join(' | ');
  if (schema.enum) return `enum(${schema.enum.length})`;
  if (schema.const !== undefined) return 'const';
  if (schema.oneOf) return 'oneOf';
  if (schema.anyOf) return 'anyOf';
  if (schema.allOf) return 'allOf';
  return schemaTypeName(schema.type || 'object');
}

function schemaTypeName(type) {
  const labels = {
    object: '对象',
    array: '数组',
    string: '字符串',
    number: '数字',
    integer: '整数',
    boolean: '布尔',
    null: '空',
  };
  return labels[type] || type || '任意';
}

function sourceLabel(source) {
  if (source === 'installed') return '已安装';
  if (source === 'market') return '市场';
  if (source === 'builtin') return '内置';
  return source || '-';
}
