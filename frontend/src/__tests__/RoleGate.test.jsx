import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import RoleGate from "../components/RoleGate";

function renderAt(path, roles) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/dashboard" element={<div>Dashboard page</div>} />
        <Route
          path="/ops"
          element={
            <RoleGate roles={roles} allowed="support">
              <div>Ops console</div>
            </RoleGate>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RoleGate / ops route", () => {
  it("redirects a normal member away from /ops", () => {
    renderAt("/ops", ["member"]);
    expect(screen.getByText("Dashboard page")).toBeInTheDocument();
    expect(screen.queryByText("Ops console")).not.toBeInTheDocument();
  });

  it("renders ops for users with the support role", () => {
    renderAt("/ops", ["member", "support"]);
    expect(screen.getByText("Ops console")).toBeInTheDocument();
  });
});
