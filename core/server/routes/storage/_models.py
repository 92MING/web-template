from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


def StorageIdField() -> Any:
    return Field(validation_alias=AliasChoices("id", "_id"))


class StorageResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class TTLInfo(StorageResponseModel):
    ttl_seconds: float | None = Field(default=None, description="Remaining TTL in seconds when the item expires.")
    ttl_state: str = Field(description="TTL state such as persistent, expiring, or expired_or_missing.")
    expire_at: str | None = Field(default=None, description="ISO-8601 expiration timestamp when the item has TTL.")


class StorageClientDescriptor(StorageResponseModel):
    name: str = Field(description="Resolved client name.")
    backend_type: str = Field(description="Backend type configured for this client.")
    is_default: bool = Field(description="Whether this entry is the default client.")
    slot: str = Field(description="Whether the client comes from a named slot or the extra section.")


class StorageClientsResponse(StorageResponseModel):
    clients: list[StorageClientDescriptor] = Field(default_factory=list)


class StorageCleanupResponse(StorageResponseModel):
    removed: int = Field(description="Number of expired or cleaned records removed by the backend.")


class DeclaredSchemaField(StorageResponseModel):
    name: str = Field(description="Declared field name.")
    declared_type: str | None = Field(default=None, description="Type declared in the stored schema.")
    required: bool = Field(description="Whether the schema marks the field as required.")
    description: str | None = Field(default=None, description="Field description extracted from the stored schema.")


class SampleField(StorageResponseModel):
    name: str = Field(description="Observed field name from sampled documents.")
    sample_types: list[str] = Field(default_factory=list, description="Observed runtime value types for the field.")
    examples: list[Any] = Field(default_factory=list, description="Sample values observed for the field.")


class LabelCount(StorageResponseModel):
    label: str = Field(description="Bucket or label name.")
    count: int = Field(description="Number of items in the bucket.")


class KeyCountBucket(StorageResponseModel):
    key: str = Field(description="Bucket key.")
    label: str = Field(description="Human-readable bucket label.")
    count: int = Field(description="Number of items in the bucket.")


class KVConfigResponse(StorageResponseModel):
    client_name: str
    backend: str
    namespace: str
    client_metadata: dict[str, Any] = Field(default_factory=dict)
    default_expire: float | None = None
    max_size: int | None = None
    list_strategy: str
    supports_binary: bool
    supports_bulk_delete: bool
    supports_pattern_search: bool
    supports_bulk_ttl: bool
    supports_copy: bool
    supports_rename: bool


class KVKeyItem(TTLInfo):
    key: str = Field(description="KV key.")


class KVKeysResponse(StorageResponseModel):
    items: list[KVKeyItem] = Field(default_factory=list)
    total: int
    page: int
    page_count: int
    page_size: int
    prefix: str
    query: str
    pattern: str
    value_kind: str = ""
    ttl_state_filter: str = ""
    min_ttl: float | None = None
    max_ttl: float | None = None


class KVSummaryTTLStats(StorageResponseModel):
    min_ttl: float | None = None
    max_ttl: float | None = None
    avg_ttl: float | None = None


class KVSummaryResponse(StorageResponseModel):
    prefix: str
    query: str
    pattern: str
    value_kind: str = ""
    ttl_state_filter: str = ""
    min_ttl: float | None = None
    max_ttl: float | None = None
    scanned_total: int
    matched_total: int
    persistent_count: int
    expiring_count: int
    ttl_stats: KVSummaryTTLStats
    ttl_buckets: list[KeyCountBucket] = Field(default_factory=list)
    key_length_buckets: list[LabelCount] = Field(default_factory=list)
    top_namespaces: list[LabelCount] = Field(default_factory=list)
    soonest_expiring: list[KVKeyItem] = Field(default_factory=list)
    sample_limit: int
    sampled_count: int
    truncated: bool
    sample_items: list[KVKeyItem] = Field(default_factory=list)
    value_sampled_count: int = 0
    value_metrics_truncated: bool = False
    sampled_value_bytes: int | None = None
    sampled_avg_value_bytes: float | None = None
    type_counts: list[LabelCount] = Field(default_factory=list)
    largest_items: list["KVInsightItem"] = Field(default_factory=list)


class KVInsightItem(TTLInfo):
    key: str
    value_kind: str
    size_bytes_estimate: int | None = None


class KVItemResponse(TTLInfo):
    key: str
    exists: bool
    value_kind: str
    display_mode: str
    value: Any = None
    pretty_json: str | None = None
    size_bytes_estimate: int | None = None
    editable: bool


class KVWriteResponse(TTLInfo):
    ok: bool
    key: str


class KVTransferResponse(TTLInfo):
    ok: bool
    action: str
    source_key: str
    target_key: str
    overwritten: bool
    source_deleted: bool | None = None


class KVDeleteResponse(StorageResponseModel):
    ok: bool
    deleted: bool
    key: str


class KVDeleteByPrefixResponse(StorageResponseModel):
    matched: int
    matched_total: int
    processed: int
    deleted: int
    truncated: bool
    keys: list[str] = Field(default_factory=list)


class KVDeleteManyItem(StorageResponseModel):
    key: str
    deleted: bool


class KVDeleteManyResponse(StorageResponseModel):
    deleted: bool
    removed: int
    items: list[KVDeleteManyItem] = Field(default_factory=list)


class KVBulkTTLItem(TTLInfo):
    key: str
    updated: bool


class KVBulkTTLResponse(StorageResponseModel):
    updated: int
    count: int
    items: list[KVBulkTTLItem] = Field(default_factory=list)


class ObjectBreadcrumb(StorageResponseModel):
    name: str
    path: str


class ObjectItemFilters(StorageResponseModel):
    type_group: str = ""
    content_type: str = ""
    min_size: int | None = None
    max_size: int | None = None
    created_from: str = ""
    created_to: str = ""
    tag: str = ""
    metadata_key: str = ""
    metadata_value: str = ""


class ObjectItem(TTLInfo):
    kind: str
    name: str
    path: str
    parent_prefix: str | None = None
    size: int
    content_type: str
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    download_url: str | None = None
    item_count: int | None = None
    previewable: bool | None = None


class ObjectConfigResponse(StorageResponseModel):
    client_name: str
    backend: str
    namespace: str
    client_metadata: dict[str, Any] = Field(default_factory=dict)
    default_expire: float | None = None
    max_size: int | None = None
    supports_preview: bool
    supports_cleanup: bool
    supports_folders: bool
    supports_copy: bool
    supports_move: bool
    supports_rename: bool
    supports_metadata_edit: bool
    supports_text_edit: bool
    supports_tags: bool
    supports_advanced_search: bool
    supports_thumbnail_view: bool
    supports_drag_move: bool
    supports_bucket_admin: bool
    folder_marker_name: str


class ObjectBucketDescriptor(StorageResponseModel):
    name: str
    backend: str
    namespace: str
    bucket: str | None = None
    folder: str | None = None
    root_path: str | None = None
    slot: str
    is_default: bool
    editable: bool
    deletable: bool
    object_count: int = 0
    folder_count: int = 0
    total_size: int = 0
    latest_updated_at: str | None = None


class ObjectBucketsResponse(StorageResponseModel):
    items: list[ObjectBucketDescriptor] = Field(default_factory=list)


class ObjectBucketWriteResponse(StorageResponseModel):
    saved: bool
    bucket: ObjectBucketDescriptor


class ObjectBucketDeleteResponse(StorageResponseModel):
    deleted: bool
    name: str
    removed_objects: int = 0


class ObjectItemsResponse(StorageResponseModel):
    prefix: str
    breadcrumbs: list[ObjectBreadcrumb] = Field(default_factory=list)
    folders: list[ObjectItem] = Field(default_factory=list)
    items: list[ObjectItem] = Field(default_factory=list)
    total: int
    offset: int
    limit: int
    recursive: bool
    query: str
    pattern: str
    filters: ObjectItemFilters


class ObjectFolderCreateResponse(StorageResponseModel):
    created: bool
    kind: str
    path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObjectUploadItem(StorageResponseModel):
    path: str
    name: str | None = None
    size: int | None = None
    content_type: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    expire_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObjectUploadSkippedItem(StorageResponseModel):
    path: str
    reason: str


class ObjectUploadResponse(StorageResponseModel):
    uploaded: list[ObjectUploadItem] = Field(default_factory=list)
    skipped: list[ObjectUploadSkippedItem] = Field(default_factory=list)


class ObjectOfficePreviewResponse(StorageResponseModel):
    path: str
    name: str
    kind: str
    format: str
    support_level: str
    preview_mode: str
    page_label: str
    page_count: int
    warnings: list[str] = Field(default_factory=list)
    pages: list[dict[str, Any]] = Field(default_factory=list)


class ObjectWriteResponse(StorageResponseModel):
    saved: bool
    path: str
    size: int
    content_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObjectMetadataUpdateResponse(StorageResponseModel):
    updated: bool
    path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObjectPathTransferResponse(StorageResponseModel):
    kind: str
    source_path: str
    target_path: str
    copied: list[str] = Field(default_factory=list)
    moved: list[str] = Field(default_factory=list)
    removed: int | None = None


class ObjectDeleteResponse(StorageResponseModel):
    deleted: bool
    path: str
    removed: int
    kind: str


class ObjectDeleteManyResponse(StorageResponseModel):
    deleted: bool
    removed: int
    items: list[ObjectDeleteResponse] = Field(default_factory=list)


class ObjectExpireResponse(TTLInfo):
    updated: bool
    path: str


class ORMConfigResponse(StorageResponseModel):
    client_name: str
    backend: str
    namespace: str
    client_metadata: dict[str, Any] = Field(default_factory=dict)
    default_expire: float | None = None
    supports_ttl: bool
    supports_drop_collection: bool
    supports_create_collection: bool
    supports_document_upsert: bool
    supports_batch_delete: bool
    supports_query_count: bool
    supports_sort: bool
    supports_index_manage: bool
    vector_client: str | None = None


class ORMCollectionSummary(StorageResponseModel):
    name: str
    typed_model: bool
    model_module: str | None = None
    model_name: str | None = None
    document_count: int | None = None
    schema_fields: list[DeclaredSchemaField] = Field(default_factory=list)


class ORMCollectionsResponse(StorageResponseModel):
    items: list[ORMCollectionSummary] = Field(default_factory=list)


class ORMSchemaResponse(StorageResponseModel):
    collection: str
    typed_model: bool
    model_module: str | None = None
    model_name: str | None = None
    model_source_path: str | None = None
    model_source: str | None = None
    schema_json_value: Any = Field(default=None, alias="schema_json")
    declared_fields: list[DeclaredSchemaField] = Field(default_factory=list)
    sample_fields: list[SampleField] = Field(default_factory=list)


class ORMIndexField(StorageResponseModel):
    field: str
    direction: str


class ORMIndexInfo(StorageResponseModel):
    name: str
    unique: bool
    fields: list[ORMIndexField] = Field(default_factory=list)
    backend: str
    managed_by_system: bool
    definition: Any = None


class ORMIndexesResponse(StorageResponseModel):
    collection: str
    items: list[ORMIndexInfo] = Field(default_factory=list)


class ORMIndexMutationResponse(StorageResponseModel):
    collection: str
    name: str
    created: bool | None = None
    deleted: bool | None = None


class ORMDocumentItem(TTLInfo):
    id: str = StorageIdField()
    document: dict[str, Any] = Field(default_factory=dict)


class ORMDocumentResponse(TTLInfo):
    collection: str
    id: str = StorageIdField()
    document: dict[str, Any] = Field(default_factory=dict)


class ORMQueryResponse(StorageResponseModel):
    collection: str
    items: list[ORMDocumentItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    has_more: bool


class ORMCollectionActionResponse(StorageResponseModel):
    collection: str
    created: bool | None = None
    deleted: bool | None = None


class ORMUpsertResponse(TTLInfo):
    ok: bool
    collection: str
    id: str = StorageIdField()


class ORMDeleteResponse(StorageResponseModel):
    deleted: bool
    collection: str
    id: str = StorageIdField()


class ORMDeleteManyItem(StorageResponseModel):
    id: str = StorageIdField()
    deleted: bool


class ORMDeleteManyResponse(StorageResponseModel):
    deleted: bool
    removed: int
    collection: str
    items: list[ORMDeleteManyItem] = Field(default_factory=list)


class ORMExpireResponse(TTLInfo):
    updated: bool
    collection: str
    id: str = StorageIdField()


class VectorFieldInfo(StorageResponseModel):
    name: str
    dim: int
    metric_type: str | None = None
    algorithm: str | None = None
    embedder_name: str | None = None
    has_bound_embedder: bool = False


class VectorConfigResponse(StorageResponseModel):
    client_name: str
    backend: str
    namespace: str
    client_metadata: dict[str, Any] = Field(default_factory=dict)
    metric_type: str
    supports_ttl: bool = True
    supports_document_upsert: bool = True
    supports_batch_delete: bool = True
    supports_score: bool
    supports_create_collection: bool
    supports_drop_collection: bool
    supports_load: bool
    supports_offload: bool
    supports_multimodal_query: bool
    embedder_services: list[str] = Field(default_factory=list)


class VectorCollectionInfo(StorageResponseModel):
    name: str
    backend_name: str
    vector_fields: list[VectorFieldInfo] = Field(default_factory=list)
    registered: bool
    item_count: int | None = None


class VectorCollectionsResponse(StorageResponseModel):
    items: list[VectorCollectionInfo] = Field(default_factory=list)


class VectorCollectionDetailResponse(StorageResponseModel):
    collection: str
    vector_fields: list[VectorFieldInfo] = Field(default_factory=list)
    metric_type: str
    scalar_fields: list[str] = Field(default_factory=list)
    item_count: int | None = None
    schema_json_value: Any = Field(default=None, alias="schema_json")
    declared_fields: list[DeclaredSchemaField] = Field(default_factory=list)
    score_kind: str


class VectorSchemaResponse(StorageResponseModel):
    collection: str
    metric_type: str
    vector_fields: list[VectorFieldInfo] = Field(default_factory=list)
    scalar_fields: list[str] = Field(default_factory=list)
    schema_json_value: Any = Field(default=None, alias="schema_json")
    declared_fields: list[DeclaredSchemaField] = Field(default_factory=list)
    sample_fields: list[SampleField] = Field(default_factory=list)


class VectorCollectionCreateResponse(StorageResponseModel):
    created: bool
    collection: str
    vector_fields: list[VectorFieldInfo] = Field(default_factory=list)


class VectorDocumentItem(TTLInfo):
    id: str = StorageIdField()
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_json: str


class VectorBrowseResponse(StorageResponseModel):
    collection: str
    items: list[VectorDocumentItem] = Field(default_factory=list)
    limit: int
    offset: int
    has_more: bool
    total: int


class VectorDocumentResponse(TTLInfo):
    collection: str
    id: str = StorageIdField()
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_json: str


class VectorUpsertResponse(TTLInfo):
    ok: bool
    collection: str
    id: str = StorageIdField()


class VectorSearchResultItem(StorageResponseModel):
    rank: int
    score: float | None = None
    id: str = StorageIdField()
    payload: dict[str, Any] = Field(default_factory=dict)
    raw_json: str


class VectorSearchResponse(StorageResponseModel):
    collection: str
    mode: str
    vector_field: str
    metric_type: str
    score_kind: str
    query_vector_dim: int
    elapsed_ms: int
    items: list[VectorSearchResultItem] = Field(default_factory=list)


class VectorDeleteManyItem(StorageResponseModel):
    id: str = StorageIdField()
    deleted: bool


class VectorDeleteManyResponse(StorageResponseModel):
    deleted: bool
    removed: int
    collection: str
    items: list[VectorDeleteManyItem] = Field(default_factory=list)


class VectorDeleteResponse(StorageResponseModel):
    deleted: bool
    collection: str
    id: str = StorageIdField()


class VectorCollectionActionResponse(StorageResponseModel):
    collection: str
    created: bool | None = None
    deleted: bool | None = None
    loaded: bool | None = None
    offloaded: bool | None = None


class VectorExpireResponse(TTLInfo):
    updated: bool
    collection: str
    id: str = StorageIdField()
