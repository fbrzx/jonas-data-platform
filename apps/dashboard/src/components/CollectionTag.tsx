import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

interface Props {
  resourceType: 'entity' | 'transform' | 'connector'
  resourceId: string
  current: string | null | undefined
  /** Called with the new collection name (or null to clear) after a successful save. */
  onSaved?: () => void
}

/**
 * Inline collection tag — shows the current collection as a small badge.
 * Click to enter edit mode: an input with datalist autocomplete appears.
 * Press Enter or blur to save (PATCH the resource). Press Escape to cancel.
 */
export default function CollectionTag({ resourceType, resourceId, current, onSaved }: Props) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(current ?? '')
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const { data: collections = [] } = useQuery({
    queryKey: ['collections'],
    queryFn: api.collections.list,
    staleTime: 30_000,
  })

  const listId = `cl-${resourceId}`

  function startEdit() {
    setValue(current ?? '')
    setEditing(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  async function save() {
    if (saving) return
    const next = value.trim() || null
    if (next === (current ?? null)) {
      setEditing(false)
      return
    }
    setSaving(true)
    try {
      const patch = { collection: next }
      if (resourceType === 'entity') await api.catalogue.update(resourceId, patch)
      else if (resourceType === 'transform') await api.transforms.update(resourceId, patch)
      else await api.connectors.update(resourceId, patch)
      await queryClient.invalidateQueries({ queryKey: [resourceType === 'entity' ? 'entities' : resourceType === 'transform' ? 'transforms' : 'integrations'] })
      await queryClient.invalidateQueries({ queryKey: ['collections'] })
      onSaved?.()
    } finally {
      setSaving(false)
      setEditing(false)
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') { e.preventDefault(); save() }
    if (e.key === 'Escape') { setEditing(false) }
  }

  if (editing) {
    return (
      <>
        <datalist id={listId}>
          {collections.map((c) => <option key={c.name} value={c.name} />)}
        </datalist>
        <input
          ref={inputRef}
          list={listId}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onBlur={save}
          onKeyDown={onKeyDown}
          placeholder="collection…"
          disabled={saving}
          className="font-mono text-[10px] bg-j-surface border border-j-accent rounded px-1.5 py-0.5 text-j-accent placeholder-j-dim focus:outline-none w-24"
        />
      </>
    )
  }

  return (
    <button
      onClick={startEdit}
      title="Click to assign collection"
      className={`font-mono text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
        current
          ? 'text-j-accent border-j-accent bg-j-accent-dim hover:border-j-accent'
          : 'text-j-dim border-dashed border-j-border hover:border-j-accent hover:text-j-accent'
      }`}
    >
      {current ?? '+ collection'}
    </button>
  )
}
