import * as Menu from '@radix-ui/react-dropdown-menu'
import {
  Check,
  ChevronRight,
  ChevronsUpDown,
  LogOut,
  Receipt,
  Terminal,
  UserPlus,
  Users,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  getCapabilities,
  getMe,
  logout,
  setBrand,
  type Capabilities,
  type Me,
} from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * The account block at the bottom of the rail, Runway's shape.
 *
 * It is deliberately NOT a copy of Runway's item list: half of theirs
 * (plans, referrals, an API tab) has no counterpart here, and a menu
 * full of links to nothing is worse than a short one. What is here maps
 * to routes that exist — `POST /brand/{name}`, `/costs`, `/studio`,
 * `POST /logout` — and the one thing that does not exist yet says so
 * instead of pretending.
 *
 * Collapsed, only the avatar shows. The name, the account line and the
 * chevron ride the same reveal as the rest of the rail.
 */
function Avatar({ me, size = 'md' }: { me: Me; size?: 'sm' | 'md' }) {
  const initials = me.display_name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase()
  return (
    <span
      className={cn(
        'grid flex-none place-items-center overflow-hidden rounded-lg bg-raised',
        'font-mono text-dim',
        size === 'md' ? 'size-9 text-[11px]' : 'size-7 text-[10px]',
      )}
    >
      {me.avatar_url ? (
        <img src={me.avatar_url} alt="" className="size-full object-cover" />
      ) : (
        initials
      )}
    </span>
  )
}

const item = cn(
  'flex w-full cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-[13px]',
  'text-text outline-none transition-colors duration-150',
  'data-[highlighted]:bg-white/7 data-[disabled]:cursor-default data-[disabled]:text-dimmer',
  'data-[disabled]:data-[highlighted]:bg-transparent',
)
const surface = cn(
  'z-90 min-w-62 rounded-2xl border border-line p-1.5',
  'bg-panel/98 backdrop-blur-2xl shadow-[0_30px_90px_-30px_rgb(0_0_0/0.95)]',
)

export function AccountMenu({ reveal }: { reveal: (node: React.ReactNode) => React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [caps, setCaps] = useState<Capabilities>({})

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null))
    getCapabilities().then(setCaps).catch(() => setCaps({}))
  }, [])

  if (!me) return null
  const devTools = caps.dev_tools === true

  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <button
          type="button"
          title={`${me.display_name} · ${me.account.display_name}`}
          className={cn(
            'flex w-full cursor-pointer items-center gap-2.5 rounded-r1 p-1.5',
            'text-left transition-colors duration-200 hover:bg-white/5',
            'data-[state=open]:bg-white/7',
          )}
        >
          <Avatar me={me} />
          {reveal(
            <span className="flex min-w-0 flex-1 items-center gap-2">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] leading-tight">
                  {me.display_name}
                </span>
                <span className="block truncate text-[11px] leading-tight text-dim">
                  {me.account.display_name} · {me.account.role}
                </span>
              </span>
              <ChevronsUpDown className="size-3.5 flex-none text-dimmer" strokeWidth={1.6} />
            </span>,
          )}
        </button>
      </Menu.Trigger>

      <Menu.Portal>
        <Menu.Content side="top" align="start" sideOffset={10} collisionPadding={12} className={surface}>
          {/* the header repeats the identity, so the menu is readable
              even when it opens off a collapsed rail showing one avatar */}
          <div className="flex items-center gap-3 border-b border-line px-2.5 py-2.5">
            <Avatar me={me} />
            <span className="min-w-0">
              <span className="block truncate text-[13px] leading-tight">{me.display_name}</span>
              <span className="block truncate text-[11px] leading-tight text-dim">{me.email}</span>
            </span>
          </div>

          <div className="py-1">
            <Menu.Sub>
              <Menu.SubTrigger className={item}>
                <Users className="size-4 text-dim" strokeWidth={1.5} />
                Switch brand
                <span className="ml-auto flex items-center gap-1.5 text-[11px] text-dim">
                  {me.account.display_name}
                  <ChevronRight className="size-3.5" strokeWidth={1.6} />
                </span>
              </Menu.SubTrigger>
              <Menu.Portal>
                <Menu.SubContent sideOffset={8} className={surface}>
                  {me.accounts.map((a) => (
                    <Menu.Item
                      key={a.slug}
                      className={item}
                      onSelect={() => void setBrand(a.slug)}
                    >
                      {a.display_name}
                      <Check
                        className={cn(
                          'ml-auto size-4',
                          a.slug === me.account.slug ? 'opacity-100' : 'opacity-0',
                        )}
                        strokeWidth={2}
                      />
                    </Menu.Item>
                  ))}
                  <p className="px-2.5 pt-1.5 pb-1 text-[11px] leading-snug text-dimmer">
                    A preference among brands you belong to — the server re-checks
                    membership either way.
                  </p>
                </Menu.SubContent>
              </Menu.Portal>
            </Menu.Sub>

            {/* Invite exists as `python -m src.accounts invite` and has no
                UI. Shown disabled and saying so beats leaving people to
                wonder where it went. */}
            <Menu.Item className={item} disabled>
              <UserPlus className="size-4" strokeWidth={1.5} />
              Invite members
              <span className="label-mono ml-auto text-[8px] text-dimmer">CLI only</span>
            </Menu.Item>
          </div>

          {devTools ? (
            <div className="border-t border-line py-1">
              <Menu.Item className={item} onSelect={() => window.location.assign('/costs')}>
                <Receipt className="size-4 text-dim" strokeWidth={1.5} />
                Spend
              </Menu.Item>
              <Menu.Item className={item} onSelect={() => window.location.assign('/studio')}>
                <Terminal className="size-4 text-dim" strokeWidth={1.5} />
                Dev console
              </Menu.Item>
            </div>
          ) : null}

          <div className="border-t border-line py-1">
            <Menu.Item className={item} onSelect={() => void logout()}>
              <LogOut className="size-4 text-dim" strokeWidth={1.5} />
              Log out
            </Menu.Item>
          </div>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
