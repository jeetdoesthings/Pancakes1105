import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from app.agents.pricing_strategist import PricingStrategist
from app.models import ExtractedRequirements, ScopeItem, AgentMessage

@pytest.fixture
def strategist():
    with patch("app.agents.pricing_strategist.ChatOpenAI"):
        return PricingStrategist()

@pytest.fixture
def sample_requirements():
    return ExtractedRequirements(
        project_name="Test Project",
        issuing_company="Test Corp",
        scope_items=[
            ScopeItem(
                item_name="enterprise firewall appliance hardware",
                description="High end firewall",
                quantity=2
            )
        ],
        budget_amount=50000.0,
        budget_currency="INR" # Base
    )

@pytest.mark.asyncio
async def test_currency_override_and_realtime_conversion(strategist, sample_requirements):
    # Mock LLM calls
    # 1. Parsing currency -> "USD"
    # 2. Extracting tax -> "0.08"
    # 3. Generating rationale -> "..."
    call_count = 0
    async def mock_side_effect(prompt_text):
        nonlocal call_count
        call_count += 1
        if "Extract the target currency" in prompt_text:
            content = "USD"
        elif "Extract the standard VAT/GST/Sales Tax rate" in prompt_text:
            content = "0.08"
        else:
            content = '{"pricing_rationale": "Test", "strategy_summary": "Test"}'
        return MagicMock(content=content)

    strategist.llm.ainvoke = AsyncMock(side_effect=mock_side_effect)
    
    # Run analysis
    strategy = await strategist.analyze(
        requirements=sample_requirements,
        additional_instructions="Please quote this in USD dollars instead of INR.",
        emit_message=None
    )
    
    assert strategy.currency == "USD"
    assert strategy.tax_rate == 0.08
    assert len(strategy.line_items) >= 1

@pytest.mark.asyncio
async def test_live_tax_rate_extraction(strategist, sample_requirements):
    # Mock LLM to return CAD and then 0.13 tax
    call_count = 0
    async def mock_side_effect(prompt_text):
        nonlocal call_count
        call_count += 1
        if "Extract the target currency" in prompt_text:
            content = "CAD"
        elif "Extract the standard VAT/GST/Sales Tax rate" in prompt_text:
            # Simulate finding 13% in search results
            content = "0.13"
        else:
            content = '{"pricing_rationale": "Test", "strategy_summary": "Test"}'
        return MagicMock(content=content)

    strategist.llm.ainvoke = AsyncMock(side_effect=mock_side_effect)
    
    strategy = await strategist.analyze(
        requirements=sample_requirements,
        additional_instructions="Convert to Canadian dollars CAD.",
        emit_message=None
    )
    
    assert strategy.currency == "CAD"
    assert strategy.tax_rate == 0.13

@pytest.mark.asyncio
async def test_value_add_trigger_on_higher_price(strategist):
    # This item: 'GIS Application & Dashboard Customization' -> GIS_APP_DEV_CUSTOM
    # Internal: cost=552500, min_margin=0.35 -> target_price=745875
    # Competitor: 720000 (GeoTech)
    # Price (745875) > Comp (720000) -> Should trigger value-adds
    
    requirements = ExtractedRequirements(
        project_name="Test",
        issuing_company="Test",
        scope_items=[
            ScopeItem(
                item_name="GIS Application & Dashboard Customization",
                description="Test",
                quantity=1
            )
        ],
        budget_amount=1000000.0,
        budget_currency="INR"
    )
    
    async def mock_side_effect(prompt_text):
        if "Extract the target currency" in prompt_text:
            content = "INR"
        else:
            content = '{"pricing_rationale": "High quality", "strategy_summary": "Defense"}'
        return MagicMock(content=content)

    strategist.llm.ainvoke = AsyncMock(side_effect=mock_side_effect)
    
    strategy = await strategist.analyze(
        requirements=requirements,
        additional_instructions="",
        emit_message=None
    )
    
    # Check if value-adds were triggered
    assert len(strategy.line_items) > 1
    assert any(item.is_value_add for item in strategy.line_items)
    # Check if strategy was MARGIN_DEFENSE
    assert any("Defending" in item.recommendation for item in strategy.competitor_analyses)
