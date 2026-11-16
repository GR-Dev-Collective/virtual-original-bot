import type { MemoryState } from '../api/memory'

export interface MemoryView {
  onOpen(handler: () => void): void
  onAdd(handler: (text: string) => void): void
  onDelete(handler: (noteId: string) => void): void
  setState(state: MemoryState): void
  setError(text: string | null): void
  isOpen(): boolean
}

function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id)
  if (!element) {
    throw new Error(`页面缺少元素 #${id}`)
  }
  return element as T
}

export function createMemoryView(): MemoryView {
  const openButton = requireElement<HTMLButtonElement>('memory-open')
  const panel = requireElement<HTMLElement>('memory-panel')
  const closeButton = requireElement<HTMLButtonElement>('memory-close')
  const summary = requireElement<HTMLElement>('memory-summary')
  const list = requireElement<HTMLUListElement>('memory-notes')
  const form = requireElement<HTMLFormElement>('memory-form')
  const input = requireElement<HTMLInputElement>('memory-input')
  const errorBox = requireElement<HTMLElement>('memory-error')

  let openHandler: () => void = () => {}
  let addHandler: (text: string) => void = () => {}
  let deleteHandler: (noteId: string) => void = () => {}

  function setError(text: string | null): void {
    errorBox.textContent = text ?? ''
    errorBox.hidden = !text
  }

  function isOpen(): boolean {
    return !panel.hidden
  }

  function setState(state: MemoryState): void {
    setError(null)
    const relationship = state.relationship
    const name = state.user_name ? `称呼：${state.user_name}` : '称呼：未设置'
    summary.textContent =
      `${name} · 关系：${relationship.stage}（好感度 ${relationship.affinity}/100，共同对话 ${relationship.interactions} 次）`

    list.replaceChildren()
    if (state.notes.length === 0) {
      const empty = document.createElement('li')
      empty.className = 'memory-notes__item'
      empty.textContent = '还没有记住的事情。'
      list.append(empty)
      return
    }
    for (const note of state.notes) {
      const item = document.createElement('li')
      item.className = 'memory-notes__item'
      const text = document.createElement('span')
      text.textContent = note.text
      const remove = document.createElement('button')
      remove.type = 'button'
      remove.className = 'memory-notes__delete'
      remove.textContent = '删除'
      remove.addEventListener('click', () => deleteHandler(note.id))
      item.append(text, remove)
      list.append(item)
    }
  }

  openButton.addEventListener('click', () => {
    panel.hidden = false
    openHandler()
    input.focus()
  })
  closeButton.addEventListener('click', () => {
    panel.hidden = true
  })
  form.addEventListener('submit', (event) => {
    event.preventDefault()
    const text = input.value.trim()
    if (!text) {
      return
    }
    input.value = ''
    addHandler(text)
  })

  return {
    onOpen(handler) {
      openHandler = handler
    },
    onAdd(handler) {
      addHandler = handler
    },
    onDelete(handler) {
      deleteHandler = handler
    },
    setState,
    setError,
    isOpen
  }
}
