// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Drag-and-drop list for a mixed outline (section headers + questions).
 * Unlike SortableList it keys on string ids and lets each row draw itself
 * (headings look different from question rows), with per-row drag disabling
 * (headers are only movable while editing sections). */
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export interface OutlineItem {
  id: string;
  disabled?: boolean;
}

function Row<T extends OutlineItem>({
  item,
  render,
}: {
  item: T;
  render: (item: T, ctx: { handle: ReactNode; isDragging: boolean }) => ReactNode;
}) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.id, disabled: item.disabled });
  const handle = item.disabled ? null : (
    <button
      type="button"
      aria-label={t("Move")}
      className="cursor-grab touch-none rounded px-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600 dark:text-slate-300 dark:hover:bg-slate-800"
      {...attributes}
      {...listeners}
    >
      <GripVertical aria-hidden className="h-4 w-4" />
    </button>
  );
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={isDragging ? "z-10 opacity-90" : ""}
    >
      {render(item, { handle, isDragging })}
    </li>
  );
}

export default function SortableOutline<T extends OutlineItem>({
  items,
  onReorder,
  renderItem,
}: {
  items: T[];
  onReorder: (items: T[]) => void;
  renderItem: (item: T, ctx: { handle: ReactNode; isDragging: boolean }) => ReactNode;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = items.findIndex((item) => item.id === active.id);
    const newIndex = items.findIndex((item) => item.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    onReorder(arrayMove(items, oldIndex, newIndex));
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={items.map((i) => i.id)} strategy={verticalListSortingStrategy}>
        <ul className="space-y-2">
          {items.map((item) => (
            <Row key={item.id} item={item} render={renderItem} />
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  );
}
