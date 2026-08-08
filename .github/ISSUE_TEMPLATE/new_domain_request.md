name: New Domain Preset Request
description: Request a new pre-curated domain preset (e.g. PostgreSQL, Docker, AWS, Figma)
title: '[Preset Request]: <Domain Name>'
labels: ['domain-preset', 'enhancement']
body:
  - type: textarea
    id: domain_details
    attributes:
      label: Software Domain Details
      description: What software ecosystem should mcp-cocktail support?
      placeholder: e.g. PostgreSQL, Docker, AWS, Figma, Blender...
    validations:
      required: true
  - type: textarea
    id: known_tools
    attributes:
      label: Known MCP Servers or CLIs
      description: List any official or community MCP servers or CLIs you know of for this domain.
      placeholder: e.g. psql CLI, postgres-mcp, pg-mcp...
    validations:
      required: false
