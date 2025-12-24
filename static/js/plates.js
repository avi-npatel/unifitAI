// Draws the barbell and the small plate strips. Plate sizes and colors mirror the server's plate list.

const SVG_NS = "http://www.w3.org/2000/svg";

// width and height are in SVG units; heights echo real plate diameters (45 lb is the largest).
const PLATE_SHAPES = {
  45: { w: 30, h: 200, cls: "plate-45" },
  35: { w: 24, h: 168, cls: "plate-35" },
  25: { w: 20, h: 138, cls: "plate-25" },
  10: { w: 14, h: 100, cls: "plate-10" },
  5: { w: 10, h: 74, cls: "plate-5" },
  2.5: { w: 8, h: 54, cls: "plate-2-5" },
};

export const plateClass = (plate) => `p-${String(plate).replace(".", "-")}`;

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

/** Draws one end of a barbell with the given plates on the sleeve (largest plate nearest the center). */
export function drawBar(target, platesPerSide, { animate = true } = {}) {
  target.replaceChildren();
  const centerY = 110;
  const sleeveStart = 250;

  target.append(
    svg("rect", { class: "shaft", x: 0, y: centerY - 6, width: 800, height: 12 }),
    svg("rect", { class: "shaft-shine", x: 0, y: centerY - 4, width: 800, height: 2 }),
    svg("rect", { class: "sleeve", x: sleeveStart, y: centerY - 12, width: 550, height: 24 }),
  );

  let x = sleeveStart + 14;
  platesPerSide.forEach((plate, index) => {
    const shape = PLATE_SHAPES[plate];
    if (!shape) return;
    const group = svg("g", { class: `plate ${shape.cls}` });
    if (animate) group.style.setProperty("--i", String(index));
    else group.style.animation = "none";
    const body = svg("rect", {
      class: "body", x, y: centerY - shape.h / 2, width: shape.w, height: shape.h, rx: 3,
    });
    body.style.fill = `var(--plate-${String(plate).replace(".", "-")})`;
    group.append(body);
    if (shape.w >= 20) {
      const label = svg("text", {
        x: x + shape.w / 2, y: centerY, "text-anchor": "middle", "dominant-baseline": "central",
        transform: `rotate(-90 ${x + shape.w / 2} ${centerY})`,
      });
      label.textContent = String(plate);
      group.append(label);
    }
    target.append(group);
    x += shape.w + 4;
  });

  target.append(svg("rect", { class: "collar", x: x + 4, y: centerY - 20, width: 16, height: 40, rx: 3 }));
}

/** A row of small colored tags showing the plates for one side of the bar. */
export function plateStrip(platesPerSide) {
  const strip = document.createElement("div");
  strip.className = "plates";
  const label = document.createElement("span");
  label.className = "plates__label";
  label.textContent = platesPerSide.length ? "Each side:" : "Each side: nothing, just the bar";
  strip.append(label);
  for (const plate of platesPerSide) {
    const tag = document.createElement("span");
    tag.className = `p ${plateClass(plate)}`;
    tag.textContent = String(plate);
    strip.append(tag);
  }
  return strip;
}

/** Plain-language version of a plate list, for screen readers. */
export function describePlates(platesPerSide) {
  if (!platesPerSide.length) return "an empty barbell";
  const counts = new Map();
  for (const plate of platesPerSide) counts.set(plate, (counts.get(plate) || 0) + 1);
  const parts = [...counts].map(([plate, n]) => `${n} ${n === 1 ? "plate" : "plates"} of ${plate} pounds`);
  return `a barbell with ${parts.join(", ")} on each side`;
}
