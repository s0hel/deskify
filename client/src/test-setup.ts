/**
 * jsdom implements neither ResizeObserver nor SVG layout, so components that
 * measure themselves need a stand-in. This reports a fixed phone-sized box,
 * which is enough for the behavioural assertions (node counts, classes, hit
 * testing). Real layout is covered by the on-device spike, not here.
 */

const RECT = { width: 375, height: 700 };

class StubResizeObserver implements ResizeObserver {
  constructor(private readonly callback: ResizeObserverCallback) {}

  observe(target: Element) {
    this.callback(
      [{ target, contentRect: RECT as DOMRectReadOnly } as ResizeObserverEntry],
      this,
    );
  }
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver ??= StubResizeObserver as unknown as typeof ResizeObserver;

if (!Element.prototype.getBoundingClientRect.call(document.body).width) {
  Element.prototype.getBoundingClientRect = function () {
    return { ...RECT, x: 0, y: 0, top: 0, left: 0, right: RECT.width, bottom: RECT.height,
      toJSON: () => ({}) } as DOMRect;
  };
}
