import { useEffect, useMemo, useState } from 'react';
import { Bot, Boxes, ChevronDown, ChevronRight, Database, LockKeyhole, Plug, RotateCw, Save } from 'lucide-react';
import { resourceLabel } from '../lib/plugins.js';

export function PluginConfigPanel({ instance, pluginPackage, onSave, onRestart }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(cloneConfig(instance.config || {}));
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});

  useEffect(() => {
    setDraft(cloneConfig(instance.config || {}));
    setError('');
    setFieldErrors({});
  }, [instance.instance_id, instance.generation, instance.config]);

  const primaryKind = useMemo(() => pluginPackage?.resources?.[0]?.kind || 'extension', [pluginPackage]);
  const configSchema = useMemo(() => findConfigSchema(pluginPackage), [pluginPackage]);
  const version = pluginPackage?.version || instance.version || '1.0.0';

  function save() {
    if (Object.keys(fieldErrors).length) {
      setError('请先修正配置字段中的 JSON 格式错误。');
      return;
    }
    setError('');
    onSave(draft);
  }

  function updateField(path, value) {
    setDraft((current) => setByPath(current, path, value));
  }

  function updateComplexField(path, value) {
    try {
      updateField(path, value.trim() ? JSON.parse(value) : null);
      setFieldErrors((current) => {
        const next = { ...current };
        delete next[path];
        return next;
      });
    } catch (event) {
      setFieldErrors((current) => ({ ...current, [path]: event.message }));
    }
  }

  return (
    <article className={open ? 'plugin-card open' : 'plugin-card'}>
      <button className="plugin-card-head" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <InstanceKindIcon kind={primaryKind} />
        <span>
          <strong>{instance.display_name}</strong>
          <small>{instance.package_id} · v{version}</small>
        </span>
      </button>
      {open && (
        <div className="plugin-card-body">
          <p>{pluginPackage?.description || '暂无插件描述'}</p>
          <div className="tag-list">
            {(pluginPackage?.resources || []).map((resource) => <span key={`${resource.kind}-${resource.id}`}>{resourceLabel(resource.kind)}</span>)}
          </div>
          {configSchema ? (
            <ConfigForm
              schema={configSchema}
              value={draft}
              onChange={updateField}
              onComplexChange={updateComplexField}
              fieldErrors={fieldErrors}
            />
          ) : (
            <JsonConfigEditor draft={draft} setDraft={setDraft} setError={setError} />
          )}
          <div className="editor-hint">加密字段由插件 schema 声明。保存时会自动忽略 “********” 脱敏占位符，避免覆盖已有密钥。</div>
          {error && <div className="field-error">{error}</div>}
          <PluginInstanceActions onSave={save} onRestart={onRestart} />
        </div>
      )}
    </article>
  );
}

function ConfigForm({ schema, value, onChange, onComplexChange, fieldErrors }) {
  const properties = schema.properties || {};
  const required = new Set(schema.required || []);
  return (
    <div className="config-form">
      {Object.entries(properties).map(([key, propertySchema]) => (
        <ConfigField
          key={key}
          path={key}
          name={key}
          schema={propertySchema}
          required={required.has(key)}
          value={getByPath(value, key)}
          onChange={onChange}
          onComplexChange={onComplexChange}
          error={fieldErrors[key]}
        />
      ))}
      {!Object.keys(properties).length && <p className="empty muted">这个插件没有声明可配置字段。</p>}
    </div>
  );
}

function ConfigField({ path, name, schema, required, value, onChange, onComplexChange, error }) {
  const type = schemaType(schema);
  const encrypted = schema['x-secret'] === true || schema['x-encrypted'] === true;
  const title = schema.title || name;
  const description = schema.description;

  return (
    <div className="config-field">
      <label>
        <span>{title}{required ? ' *' : ''}</span>
        {encrypted && <em><LockKeyhole size={12} />加密</em>}
      </label>
      {description && <small>{description}</small>}
      {renderFieldInput({ path, type, encrypted, schema, value, onChange, onComplexChange })}
      {error && <div className="field-error compact-error">JSON 格式错误：{error}</div>}
    </div>
  );
}

function renderFieldInput({ path, type, encrypted, schema, value, onChange, onComplexChange }) {
  if (schema.enum) {
    return (
      <select value={value ?? ''} onChange={(event) => onChange(path, event.target.value)}>
        <option value="">未选择</option>
        {schema.enum.map((item) => <option key={String(item)} value={item}>{String(item)}</option>)}
      </select>
    );
  }
  if (type === 'boolean') {
    return <label className="checkbox-field"><input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(path, event.target.checked)} />启用</label>;
  }
  if (type === 'integer' || type === 'number') {
    return (
      <input
        type="number"
        value={value ?? ''}
        min={schema.minimum}
        max={schema.maximum}
        onChange={(event) => onChange(path, numberValue(event.target.value, type))}
      />
    );
  }
  if (type === 'object' || type === 'array') {
    return (
      <ComplexJsonInput
        path={path}
        value={value ?? (type === 'array' ? [] : {})}
        onComplexChange={onComplexChange}
      />
    );
  }
  return (
    <input
      type={encrypted ? 'password' : 'text'}
      value={value ?? ''}
      placeholder={schema.default ?? ''}
      onChange={(event) => onChange(path, nullableValue(event.target.value, schema))}
    />
  );
}

function ComplexJsonInput({ path, value, onComplexChange }) {
  const [text, setText] = useState(formatConfig(value));

  useEffect(() => {
    setText(formatConfig(value));
  }, [path, value]);

  return (
    <textarea
      className="config-editor compact-editor"
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        onComplexChange(path, event.target.value);
      }}
      spellCheck="false"
    />
  );
}

function JsonConfigEditor({ draft, setDraft, setError }) {
  return (
    <>
      <label>配置 JSON</label>
      <textarea
        className="config-editor"
        value={formatConfig(draft)}
        onChange={(event) => {
          try {
            setDraft(event.target.value.trim() ? JSON.parse(event.target.value) : {});
            setError('');
          } catch (error) {
            setError(`JSON 格式错误：${error.message}`);
          }
        }}
        spellCheck="false"
      />
    </>
  );
}

function findConfigSchema(pluginPackage) {
  if (!pluginPackage?.config_schema_ref) return null;
  return (pluginPackage.schemas || []).find((schema) => schema.schema_ref === pluginPackage.config_schema_ref)?.json_schema || null;
}

function schemaType(schema) {
  const type = Array.isArray(schema.type) ? schema.type.find((item) => item !== 'null') : schema.type;
  return type || 'string';
}

function numberValue(value, type) {
  if (value === '') return null;
  return type === 'integer' ? Number.parseInt(value, 10) : Number.parseFloat(value);
}

function nullableValue(value, schema) {
  return Array.isArray(schema.type) && schema.type.includes('null') && value === '' ? null : value;
}

function cloneConfig(config) {
  return JSON.parse(JSON.stringify(config || {}));
}

function formatConfig(config) {
  return JSON.stringify(config ?? {}, null, 2);
}

function getByPath(source, path) {
  return path.split('.').reduce((current, part) => current?.[part], source);
}

function setByPath(source, path, value) {
  const next = cloneConfig(source);
  const parts = path.split('.');
  let target = next;
  for (const part of parts.slice(0, -1)) {
    target[part] = target[part] && typeof target[part] === 'object' ? target[part] : {};
    target = target[part];
  }
  target[parts.at(-1)] = value;
  return next;
}

function PluginInstanceActions({ onSave, onRestart, disabled }) {
  return (
    <div className="plugin-actions">
      <button className="mini-button" onClick={onRestart} disabled={disabled}><RotateCw size={14} />重启</button>
      <button className="mini-button primary-mini" onClick={onSave} disabled={disabled}><Save size={14} />保存</button>
    </div>
  );
}

function InstanceKindIcon({ kind }) {
  if (kind === 'model') return <Bot size={14} />;
  if (kind === 'memory') return <Database size={14} />;
  if (kind === 'tool') return <Plug size={14} />;
  return <Boxes size={14} />;
}
