import { LanguageSwitcher } from "./LanguageSwitcher";

export function Sidebar() {
  return (
    <aside className="w-72 shrink-0 border-r border-zinc-800 bg-zinc-900 flex flex-col">
      <header className="p-4 border-b border-zinc-800">
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-semibold flex items-center gap-2 min-w-0">
            <img
              src="/logo/chatrpg-logo-dark-transparent.png"
              alt=""
              aria-hidden="true"
              className="h-7 w-7 shrink-0 object-contain"
            />
            <span className="truncate">ChatRPG</span>
          </h1>
          <LanguageSwitcher />
        </div>
        <p className="text-xs text-zinc-500 mt-1">v0.1.0-alpha</p>
      </header>

      <a
        href="/admin"
        className="mx-3 mt-3 px-3 py-1.5 rounded-lg border border-zinc-800 hover:border-zinc-600 text-zinc-300 text-xs font-medium transition text-center"
      >
        ⚙ Admin
      </a>

      <div className="flex-1" />
    </aside>
  );
}
