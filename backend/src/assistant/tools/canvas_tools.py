from __future__ import annotations

from typing import Any

from src.assistant.types import ToolEffect


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


class CanvasAssistantCanvasInspectionTools:
    def __init__(self, service: Any | None = None) -> None:
        self.service = service

    async def inspect_graph(self, document_id: str, user_id: str) -> dict[str, Any]:
        # inspect_graph 返回“可再压缩”的事实快照；真正进 prompt 前还会二次裁剪。
        if self.service is None:
            return {"document": {"id": document_id}, "items": [], "connections": [], "counts": {"items": 0, "connections": 0}}
        graph = await self.service.get_graph(document_id, user_id)
        items = [self._serialize_item(item) for item in list(graph.get("items") or [])]
        connections = [self._serialize_connection(connection) for connection in list(graph.get("connections") or [])]
        return {
            "document": self._serialize_document(graph.get("document")),
            "items": items,
            "connections": connections,
            "counts": {"items": len(items), "connections": len(connections)},
        }

    async def find_items(self, document_id: str, user_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        snapshot = await self.inspect_graph(document_id, user_id)
        normalized_query = _normalize_text(query)
        if not normalized_query:
            return []
        scored: list[tuple[int, dict[str, Any]]] = []
        for item in list(snapshot.get("items") or []):
            title = _normalize_text(item.get("title"))
            item_type = _normalize_text(item.get("item_type"))
            content = item.get("content") or {}
            text_blob = " ".join(
                [
                    title,
                    item_type,
                    _normalize_text(content.get("text")),
                    _normalize_text(content.get("prompt")),
                    _normalize_text(content.get("text_preview")),
                ]
            )
            score = 0
            if title and normalized_query in title:
                score += 5
            if item_type and normalized_query in item_type:
                score += 3
            if normalized_query in text_blob:
                score += 2
            if score:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    async def read_item_detail(self, document_id: str, user_id: str, item_id: str) -> dict[str, Any]:
        if self.service is None:
            return {"id": item_id}
        item = await self.service.get_item(item_id, user_id)
        serialized = self._serialize_item(item)
        serialized["document_id"] = document_id
        return serialized

    async def read_neighbors(self, document_id: str, user_id: str, item_ids: list[str]) -> dict[str, Any]:
        snapshot = await self.inspect_graph(document_id, user_id)
        id_set = {str(item_id).strip() for item_id in item_ids if str(item_id).strip()}
        connections = list(snapshot.get("connections") or [])
        neighbor_ids = set()
        for connection in connections:
            source_item_id = str(connection.get("source_item_id") or "").strip()
            target_item_id = str(connection.get("target_item_id") or "").strip()
            if source_item_id in id_set and target_item_id:
                neighbor_ids.add(target_item_id)
            if target_item_id in id_set and source_item_id:
                neighbor_ids.add(source_item_id)
        items = [item for item in list(snapshot.get("items") or []) if str(item.get("id") or "").strip() in neighbor_ids]
        return {"items": items, "connections": connections}

    def _serialize_document(self, document: Any) -> dict[str, Any]:
        if document is None:
            return {}
        if isinstance(document, dict):
            return dict(document)
        if hasattr(document, "to_dict"):
            return dict(document.to_dict())
        return {"id": getattr(document, "id", ""), "title": getattr(document, "title", "")}

    def _serialize_item(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return {
                "id": str(item.get("id") or ""),
                "item_type": item.get("item_type"),
                "title": item.get("title", ""),
                "content": dict(item.get("content") or {}),
            }
        base = dict(item.to_dict()) if hasattr(item, "to_dict") else {}
        return {
            "id": str(base.get("id", getattr(item, "id", ""))),
            "item_type": base.get("item_type", getattr(item, "item_type", "")),
            "title": base.get("title", getattr(item, "title", "")),
            "content": dict(base.get("content_json", getattr(item, "content_json", {})) or {}),
        }

    def _serialize_connection(self, connection: Any) -> dict[str, Any]:
        if isinstance(connection, dict):
            return {
                **connection,
                "id": str(connection.get("id") or ""),
                "source_item_id": str(connection.get("source_item_id") or ""),
                "target_item_id": str(connection.get("target_item_id") or ""),
            }
        if hasattr(connection, "to_dict"):
            payload = dict(connection.to_dict())
            payload["id"] = str(payload.get("id") or "")
            payload["source_item_id"] = str(payload.get("source_item_id") or "")
            payload["target_item_id"] = str(payload.get("target_item_id") or "")
            return payload
        return {
            "id": str(getattr(connection, "id", "")),
            "source_item_id": str(getattr(connection, "source_item_id", "")),
            "target_item_id": str(getattr(connection, "target_item_id", "")),
            "source_handle": getattr(connection, "source_handle", ""),
            "target_handle": getattr(connection, "target_handle", ""),
        }


class CanvasAssistantCanvasExecutionTools:
    def __init__(self, service: Any | None = None) -> None:
        self.service = service

    async def _commit_if_possible(self) -> None:
        commit = getattr(self.service, "commit", None)
        if callable(commit):
            await commit()

    async def create_item(self, document_id: str, user_id: str, item: dict[str, Any]) -> dict[str, Any]:
        # 执行工具统一返回标准化 effect，前端和 observation 节点只依赖这个结构，不猜测具体结果形状。
        created = item if self.service is None else await self.service.create_item(document_id, user_id, item)
        await self._commit_if_possible()
        item_id = str(created.get("id") or "") if isinstance(created, dict) else str(getattr(created, "id", ""))
        effect = ToolEffect(mutated=True, created_item_ids=[item_id] if item_id else [], summary="已创建节点。")
        return {"item": created, "effect": effect}

    async def update_item(self, document_id: str, user_id: str, item_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        updated = {"id": item_id, **patch} if self.service is None else await self.service.update_item(document_id, item_id, user_id, patch)
        await self._commit_if_possible()
        normalized_id = str(updated.get("id") or "") if isinstance(updated, dict) else str(getattr(updated, "id", item_id))
        effect = ToolEffect(mutated=True, updated_item_ids=[normalized_id] if normalized_id else [], summary="已更新节点。")
        return {"item": updated, "effect": effect}

    async def delete_items(self, document_id: str, user_id: str, item_ids: list[str]) -> dict[str, Any]:
        if self.service is not None:
            for item_id in item_ids:
                await self.service.delete_item(document_id, item_id, user_id)
            await self._commit_if_possible()
        effect = ToolEffect(mutated=True, deleted_item_ids=item_ids, summary="已删除节点。")
        return {"deleted_item_ids": item_ids, "effect": effect}

    async def create_connection(self, document_id: str, user_id: str, connection: dict[str, Any]) -> dict[str, Any]:
        created = connection if self.service is None else await self.service.create_connection(document_id, user_id, connection)
        await self._commit_if_possible()
        connection_id = str(created.get("id") or "") if isinstance(created, dict) else str(getattr(created, "id", ""))
        effect = ToolEffect(mutated=True, created_connection_ids=[connection_id] if connection_id else [], summary="已创建连线。")
        return {"connection": created, "effect": effect}

    async def delete_connections(self, document_id: str, user_id: str, connection_ids: list[str]) -> dict[str, Any]:
        if self.service is not None:
            for connection_id in connection_ids:
                await self.service.delete_connection(document_id, connection_id, user_id)
            await self._commit_if_possible()
        effect = ToolEffect(mutated=True, deleted_connection_ids=connection_ids, summary="已删除连线。")
        return {"deleted_connection_ids": connection_ids, "effect": effect}
