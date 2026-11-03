// An on-screen keyboard: the kiosk has no other, and a browser's own needs a
// desktop this Pi doesn't run. Between its layers it has every printable ASCII
// character, which is everything a WPA password can contain.
export const LAYERS = {
  lower: ["qwertyuiop", "asdfghjkl", "zxcvbnm"],
  upper: ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"],
  symbols: ["1234567890", "@#$%&*-+()", "!\"':;/?"],
  more: ["~`|\\^_=[]", "{}<>,."],
};

const LEFT_OF_LAST_ROW = { lower: "upper", upper: "lower", symbols: "more", more: "symbols" };
const LABELS = { upper: "⇧", lower: "⇧", symbols: "#+=", more: "#+=" };

export function buildKeyboard(host, onChange) {
  let layer = "lower";

  function key(label, press, kind) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = kind ? `key ${kind}` : "key";
    button.textContent = label;
    button.addEventListener("click", press);
    return button;
  }

  function type(character) {
    onChange((text) => text + character);
    if (layer === "upper") show("lower");
  }

  function show(next) {
    layer = next;
    const rows = LAYERS[layer].map((letters, index, all) => {
      const row = document.createElement("div");
      row.className = "key-row";
      const keys = [...letters].map((c) => key(c, () => type(c)));
      if (index === all.length - 1) {
        keys.unshift(key(LABELS[LEFT_OF_LAST_ROW[layer]], () => show(LEFT_OF_LAST_ROW[layer]), "special"));
        keys.push(key("⌫", () => onChange((text) => text.slice(0, -1)), "special"));
      }
      row.append(...keys);
      return row;
    });
    const last = document.createElement("div");
    last.className = "key-row";
    const letters = layer === "lower" || layer === "upper";
    last.append(
      key(letters ? "123" : "abc", () => show(letters ? "symbols" : "lower"), "special"),
      key("space", () => type(" "), "space"),
    );
    host.replaceChildren(...rows, last);
  }

  show("lower");
  return () => show("lower");
}
