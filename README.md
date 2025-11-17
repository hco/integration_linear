> **Note:** This integration is still a work in progress. Features and configuration options may change in future updates. There might be bugs :D

# Linear Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Integrate your Linear workspace with Home Assistant to manage your project issues directly from your smart home dashboard. This integration creates Todo list entities for each Linear team, allowing you to view, create, update, and complete issues without leaving Home Assistant.

## Features

- **Todo List Integration**: View your Linear issues as todo items in Home Assistant's native Todo list interface
- **Multi-Team Support**: Configure multiple Linear teams, each appearing as a separate todo list entity
- **Create Issues**: Add new issues directly from Home Assistant
- **Update Issues**: Modify issue titles, descriptions, and due dates
- **Status Management**: Mark issues as completed or move them back to todo status- **Configurable Workflow States**: Map your Linear workflow states to todo/completed/removed statuses

## Installation

This integration is not yet available in the HACS default store, but you can install it as a custom repository.

### Prerequisites

- Home Assistant 2025.11 or later
- [HACS](https://hacs.xyz/) installed and configured

### Installing via HACS (Custom Repository)

1. **Open HACS** in your Home Assistant interface
2. Click on the **three dots** (⋮) in the top right corner
3. Select **"Custom repositories"**
4. Enter the following information:
   - **Repository**: `https://github.com/hco/integration_linear`
   - **Category**: Select **"Integration"**
5. Click **"ADD"**
6. Return to the HACS **Integrations** page
7. Search for **"Linear Integration"**
8. Click on the integration and then click **"Download"**
9. **Restart Home Assistant** to activate the integration

### Manual Installation

If you prefer to install manually:

1. Download the latest release from the [releases page](https://github.com/hco/integration_linear/releases)
2. Extract the `custom_components/integration_linear` folder
3. Copy it to your Home Assistant `custom_components` directory
4. Restart Home Assistant

## Configuration

### Getting Your Linear API Token

1. Go to [Linear Settings](https://linear.app/settings/api)
2. Navigate to **API** section
3. Click **"Create API key"**
4. Give it a name (e.g., "Home Assistant")
5. Copy the generated API token (you'll only see it once!)

### Setting Up the Integration

1. In Home Assistant, go to **Settings** → **Devices & Services**
2. Click **"Add Integration"**
3. Search for **"Linear Integration"** and select it
4. Enter your **Linear API Token**
5. Select the **teams** you want to integrate
6. For each team, configure:
   - **Todo States**: Select one or more workflow states that represent active/incomplete issues
   - **Completed State**: Select the workflow state that represents completed issues (e.g., "Done")
   - **Removed State**: Select the workflow state for removed/cancelled issues (e.g., "Cancelled")
7. Click **"Submit"** to complete the setup

The integration will automatically create a todo list entity for each configured team (e.g., `todo.linear_engineering`, `todo.linear_design`).

## Usage

### Viewing Issues

Once configured, you can view your Linear issues in Home Assistant:

- **Lovelace UI**: Add a Todo card to your dashboard
- **Entities**: Each team appears as a `todo.linear_<team_name>` entity
- **States**: Issues in "todo states" appear as incomplete, issues in "completed state" appear as completed

### Creating Issues

You can create new Linear issues directly from Home Assistant:

1. Open the todo list entity for your team
2. Click **"Add item"** or use the create todo service
3. Enter the issue title
4. Optionally add a description and due date
5. The issue will be created in Linear with the first configured "todo state"

### Updating Issues

- **Mark as Complete**: Check off an issue to move it to the "completed state" in Linear
- **Update Description**: Edit the description directly in the todo list
- **Change Due Date**: Update the due date, and it will sync to Linear
- **Reopen**: Uncheck a completed issue to move it back to the first "todo state"

### Creating Issues with Advanced Features

The integration provides a custom service `integration_linear.create_issue` that offers more features than the standard todo creation:

```yaml
service: integration_linear.create_issue
data:
  team_identifier: "ENG" # Team identifier (e.g., "ENG", "DESIGN") - easier than team_id
  title: "Fix critical bug"
  description: "This is a critical bug that needs immediate attention"
  assignee_email: "user@example.com" # Assigns to user with this email (must exist)
  label_names: # Adds labels by name (must exist)
    - "bug"
    - "critical"
  state_name_or_id: "In Progress" # Sets status by name or ID
  due_date: "2025-12-31" # Optional due date (YYYY-MM-DD format)
```

**Service Parameters:**

- `team_id` or `team_identifier` (one required):
  - `team_id`: The Linear team ID (UUID) where the issue will be created
  - `team_identifier`: The team identifier/prefix (e.g., "ENG", "DESIGN") - much easier to use!
- `title` (required): The issue title
- `assignee_email` (optional): Email address of the user to assign. If the user doesn't exist, the service will throw an error.
- `label_names` (optional): List of label names to add to the issue. All labels must exist for the team, otherwise an error is thrown.
- `state_name_or_id` (optional): The workflow state name or ID to set. If the state doesn't exist, an error is thrown.
- `description` (optional): Issue description
- `due_date` (optional): Due date in YYYY-MM-DD format
- `entry_id` (optional): Config entry ID if you have multiple Linear integrations configured

**Note:** You can use either `team_id` or `team_identifier`, but not both. The `team_identifier` is the team's issue prefix (like "ENG" for Engineering), which is much easier to remember than a UUID.

### Automations

You can use the todo entities in automations:

```yaml
automation:
  - alias: "Notify when Linear issue is completed"
    trigger:
      - platform: state
        entity_id: todo.linear_engineering
        to: "completed"
    action:
      - service: notify.mobile_app
        data:
          message: "Linear issue completed!"

  - alias: "Create Linear issue from sensor"
    trigger:
      - platform: numeric_state
        entity_id: sensor.temperature
        above: 30
    action:
      - service: integration_linear.create_issue
        data:
          team_identifier: "ENG" # Use team identifier instead of team_id
          title: "Temperature too high"
          description: "Temperature sensor {{ states('sensor.temperature') }}°C exceeded threshold"
          assignee_email: "admin@example.com"
          label_names:
            - "alert"
            - "temperature"
          state_name_or_id: "Todo"
```

## Troubleshooting

### Integration Not Appearing

- Ensure you've restarted Home Assistant after installation
- Check that the integration is in `custom_components/integration_linear`
- Verify HACS installation if using custom repository method

### Authentication Errors

- Verify your API token is correct and hasn't expired
- Check that the token has the necessary permissions in Linear
- Try creating a new API token if issues persist

### Issues Not Syncing

- Check the Home Assistant logs for any error messages
- Verify your team and state configurations are correct
- Ensure the selected states exist in your Linear workspace

### No Issues Showing

- Verify that you have issues in the selected "todo states" or "completed state"
- Check that the team selection includes teams with issues
- Review the coordinator update interval in the integration settings

## Support

- **Issues**: Report bugs or request features on [GitHub Issues](https://github.com/hco/integration_linear/issues)
- **Documentation**: Check the [GitHub repository](https://github.com/hco/integration_linear) for more details

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
