### Fixed

- Durable provider and provider-catalog bootstrap reports now expose the resolved persisted agent identity in both `selected_agent_ids` and `enabled_agent_ids`. Legacy discovered-agent migration therefore no longer reports two identifier generations for the same selected endpoint; ephemeral bootstrap reports continue to use generated identities because no persisted identity exists.
