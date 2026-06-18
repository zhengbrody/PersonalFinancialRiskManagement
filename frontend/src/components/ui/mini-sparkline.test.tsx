import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { MiniSparkline } from "./mini-sparkline";

describe("MiniSparkline", () => {
  it("renders nothing with fewer than 2 points", () => {
    expect(render(<MiniSparkline data={[5]} />).container).toBeEmptyDOMElement();
    expect(render(<MiniSparkline data={undefined} />).container).toBeEmptyDOMElement();
    expect(render(<MiniSparkline data={[Number.NaN, 1]} />).container).toBeEmptyDOMElement();
  });

  it("renders a chart container once there are >= 2 finite points", () => {
    const { container } = render(<MiniSparkline data={[1, 2, 3]} />);
    expect(container.firstChild).not.toBeNull();
  });
});
