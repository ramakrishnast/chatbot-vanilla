import type { ModelInfo } from "../types";

interface Props {
  models: ModelInfo[];
  value: string | null;
  disabled: boolean;
  onChange: (name: string) => void;
  onRefresh: () => void;
}

export function ModelPicker({ models, value, disabled, onChange, onRefresh }: Props) {
  const installed = models.some((m) => m.name === value);

  return (
    <div className="model-picker">
      <select
        aria-label="Model"
        value={value ?? ""}
        disabled={disabled || (models.length === 0 && !value)}
        onChange={(e) => onChange(e.target.value)}
      >
        {!value && <option value="">No models</option>}
        {value && !installed && <option value={value}>{value} (not installed)</option>}
        {models.map((m) => (
          <option key={m.name} value={m.name}>
            {m.name}
            {m.parameter_size ? ` · ${m.parameter_size}` : ""}
            {m.capabilities.includes("thinking") ? " · thinks" : ""}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="icon-button"
        aria-label="Refresh model list"
        title="Refresh model list"
        disabled={disabled}
        onClick={onRefresh}
      >
        ↻
      </button>
    </div>
  );
}
