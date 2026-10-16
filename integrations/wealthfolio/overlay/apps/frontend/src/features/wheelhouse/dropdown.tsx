import {
  Children,
  isValidElement,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@wealthfolio/ui/components/ui/select";
import "./dropdown.css";

interface OptionProps {
  value?: string | number;
  disabled?: boolean;
  children: ReactNode;
}

/** Declarative options consumed by Dropdown; never renders a native popup. */
export function DropdownOption(_props: OptionProps) {
  return null;
}

function optionText(children: ReactNode): string {
  return Children.toArray(children)
    .map((child) => {
      if (typeof child === "string" || typeof child === "number")
        return String(child);
      if (isValidElement<{ children?: ReactNode }>(child))
        return optionText(child.props.children);
      return "";
    })
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

interface DropdownProps {
  children: ReactNode;
  value?: string | number;
  defaultValue?: string | number;
  onValueChange?: (value: string) => void;
  name?: string;
  required?: boolean;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
}

export function Dropdown({
  children,
  value,
  defaultValue,
  onValueChange,
  name,
  required,
  disabled,
  id,
  "aria-label": ariaLabel,
}: DropdownProps) {
  const generatedId = useId();
  const emptyValue = `empty:${generatedId}`;
  const trigger = useRef<HTMLButtonElement>(null);
  const [invalid, setInvalid] = useState(false);
  const [localValue, setLocalValue] = useState<string | undefined>(
    defaultValue === undefined ? undefined : String(defaultValue),
  );
  const options = Children.toArray(children).flatMap((child) => {
    if (!isValidElement<OptionProps>(child)) return [];
    const label = optionText(child.props.children);
    return [
      {
        value:
          child.props.value === undefined ? label : String(child.props.value),
        label,
        disabled: child.props.disabled ?? false,
      },
    ];
  });
  const placeholder = options.find(
    (option) => option.value === "" && (required || option.disabled),
  );
  const available = options.filter((option) => option !== placeholder);
  const initial =
    defaultValue === undefined
      ? (options[0]?.value ?? "")
      : String(defaultValue);
  const selected =
    value === undefined ? (localValue ?? initial) : String(value);
  const radixValue =
    selected === "" && available.some((option) => option.value === "")
      ? emptyValue
      : selected;
  const display = options.find((option) => option.value === selected)?.label;
  useEffect(() => {
    const form = trigger.current?.form;
    if (!form || value !== undefined) return;
    const reset = () => {
      setLocalValue(undefined);
      setInvalid(false);
    };
    form.addEventListener("reset", reset);
    return () => form.removeEventListener("reset", reset);
  }, [value]);

  return (
    <>
      <Select
        value={radixValue}
        disabled={disabled || available.length === 0}
        onValueChange={(next) => {
          const actual = next === emptyValue ? "" : next;
          setInvalid(false);
          if (value === undefined) setLocalValue(actual);
          onValueChange?.(actual);
        }}
      >
        <SelectTrigger
          ref={trigger}
          id={id ?? generatedId}
          aria-label={ariaLabel}
          aria-required={required}
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? `${generatedId}-error` : undefined}
          className="wh-select-trigger"
          title={display}
        >
          <SelectValue
            placeholder={placeholder?.label ?? "No options available"}
          />
        </SelectTrigger>
        <SelectContent
          className="wh-select-content"
          position="popper"
          sideOffset={5}
          collisionPadding={{ top: 12, right: 12, bottom: 80, left: 12 }}
        >
          {available.map((option) => (
            <SelectItem
              key={option.value}
              value={option.value === "" ? emptyValue : option.value}
              disabled={option.disabled}
              textValue={option.label}
              className="wh-select-option"
            >
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {name && (
        <select
          className="wh-select-form-control"
          aria-hidden="true"
          tabIndex={-1}
          name={name}
          required={required}
          disabled={disabled}
          value={selected}
          onChange={() => {}}
          onInvalid={(event) => {
            event.preventDefault();
            setInvalid(true);
            trigger.current?.focus();
          }}
        >
          <option value="" />
          {options
            .filter((option) => option.value !== "")
            .map((option) => (
              <option
                key={option.value}
                value={option.value}
                disabled={option.disabled}
              >
                {option.label}
              </option>
            ))}
        </select>
      )}
      {invalid && (
        <span
          className="wh-select-error"
          id={`${generatedId}-error`}
          role="alert"
        >
          Choose an option to continue.
        </span>
      )}
    </>
  );
}
