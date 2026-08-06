import Link from "next/link";

const links = [
  { href: "/", label: "Dashboard" },
  { href: "/signals", label: "Signals" },
  { href: "/trades", label: "Trades" },
];

export function Nav() {
  return (
    <nav className="border-b border-zinc-800 bg-zinc-950">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
        <span className="text-lg font-semibold text-emerald-400">
          Trading MVP
        </span>
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className="text-sm text-zinc-400 transition hover:text-white"
          >
            {l.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
