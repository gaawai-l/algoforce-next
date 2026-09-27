import { LANGUAGE_STORAGE_KEY } from "@/i18n/i18n";
import { useSettingsContext } from "@/lib/settings-provider";
import { useTranslation } from "react-i18next";
import { useWheelhouseText, wheelhouseLocale } from "./i18n";
import "./language-toggle.css";

export function LanguageToggle() {
  const { i18n } = useTranslation();
  const { text } = useWheelhouseText();
  const { updateSettings } = useSettingsContext();
  const active = wheelhouseLocale(i18n.resolvedLanguage ?? i18n.language);
  const choose = (next: "en" | "zh") => {
    if (i18n.language === next) return;
    const previous = i18n.language;
    document.documentElement.lang = next;
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
    } catch {
      // The settings write below remains the persisted source.
    }
    void i18n.changeLanguage(next).then(() =>
      updateSettings({ language: next }).catch(() => {
        document.documentElement.lang = previous;
        void i18n.changeLanguage(previous);
      }),
    );
  };
  return (
    <div className="wh-lang" role="group" aria-label={text("lang.group")}>
      <button type="button" aria-pressed={i18n.language === "en"} onClick={() => choose("en")}>
        EN
      </button>
      <button
        type="button"
        aria-pressed={active === "zh" && i18n.language === "zh"}
        onClick={() => choose("zh")}
      >
        中文
      </button>
    </div>
  );
}
